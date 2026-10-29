"""Allow / ask / deny policy for tool calls. Used by the PreToolUse hook and the headless SDK runner.

Order: every deny rule first, then ask rules. An ask whose (rule, target) has an unexpired grant in the
ApprovalStore becomes allow. Autonomy can add asks (supervised) but never turns a deny into an allow.
"""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import config, paths, shellparse
from .approvals import ApprovalStore

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}
INTERPRETERS = {"python", "python3", "py", "perl", "ruby", "node", "rscript"}


@dataclass
class Decision:
    action: Literal["allow", "ask", "deny"]
    reason: str = ""
    rule: str = ""


ALLOW = Decision("allow")


@functools.lru_cache(maxsize=1)
def _reviewer_scope() -> tuple[str, ...]:
    try:
        from .agent_registry import load_agents
        return tuple(load_agents()["reviewer"].write_scope or [".research-agent/reviews"])
    except Exception:  # registry unreadable: fall back to the documented default
        return (".research-agent/reviews",)


def _tool_paths(tool: str, inp: dict, cwd: Path) -> list[Path]:
    keys = ("file_path", "notebook_path", "path")
    out = [shellparse.resolve_path(str(inp[k]), cwd) for k in keys if inp.get(k)]
    if tool == "Glob" and inp.get("pattern") and not inp.get("path"):
        base = str(inp["pattern"]).split("*", 1)[0]
        if base:
            out.append(shellparse.resolve_path(base, cwd))
    return out


def _bash_path_tokens(cmd: str, cwd: Path) -> list[Path]:
    out = []
    for seg in shellparse.segments(cmd):
        for t in seg[1:]:
            if t.startswith("-") or t in shellparse.REDIRECTS:
                continue
            if "/" in t or "\\" in t or t.startswith("~") or ".research-agent" in t:
                out.append(shellparse.resolve_path(t.split("=", 1)[-1], cwd))
    return out


def _within_any(p: Path, roots: list[Path]) -> Path | None:
    return next((r for r in roots if paths.is_within(p, r)), None)


def _state_root_of(p: Path) -> Path | None:
    parts = p.parts
    if paths.STATE_DIRNAME not in parts:
        return None
    i = parts.index(paths.STATE_DIRNAME)
    return Path(*parts[: i + 1])


def _git_subcommand(s: list[str]) -> str:
    i = 1
    while i < len(s):
        t = s[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t
    return ""


def _flag_value(s: list[str], flag: str) -> str | None:
    for i, t in enumerate(s):
        if t == flag and i + 1 < len(s):
            return s[i + 1]
        if t.startswith(flag + "="):
            return t.split("=", 1)[1]
    return None


def _is_ra(s: list[str], *sub: str) -> bool:
    if not s or os.path.basename(s[0]).lower().removesuffix(".exe") not in ("ra", "ra.cmd"):
        if not (len(s) > 2 and s[1] == "-m" and s[2] == "research_agent"):
            return False
        s = ["ra", *s[3:]]
    return s[1 : 1 + len(sub)] == list(sub)


def evaluate(tool: str, tool_input: dict, cwd: Path, cfg: dict, project: Path | None,
             agent: str | None = None, approvals: ApprovalStore | None = None) -> Decision:
    cwd = Path(cwd)
    tool_input = tool_input or {}
    agent_name = (agent or "").split(":")[-1]
    root = Path(project) if project else None
    cmd = str(tool_input.get("command", "")) if tool == "Bash" else ""
    segs = [shellparse.strip_wrappers(s) for s in shellparse.segments(cmd)] if cmd else []

    protected = [root / p for p in config.get(cfg, "data.protected_paths", [])] if root else []
    sensitive = [root / p for p in config.get(cfg, "data.sensitive_paths", [])] if root else []
    targets = (_tool_paths(tool, tool_input, cwd) if tool in WRITE_TOOLS else []) + (shellparse.write_targets(cmd, cwd) if cmd else [])
    touched = (_tool_paths(tool, tool_input, cwd) if tool in READ_TOOLS | WRITE_TOOLS else []) + (_bash_path_tokens(cmd, cwd) if cmd else [])

    # ---- deny ----------------------------------------------------------------------------------------------------
    for t in targets:
        hit = _within_any(t, protected)
        if hit:
            return Decision("deny", f"{t} is inside protected raw data ({hit.relative_to(root)}); write derived data elsewhere", "protected-write")

    boundary = root or cwd
    for s in segs:
        if s and shellparse.verb(s) == "rm" and any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive", t) for t in s[1:]):
            for a in shellparse._args(s):
                p = shellparse.resolve_path(a, cwd)
                if a in ("/", "~", "~/", "$HOME", "*", "/*", ".") and (a != "." or p == boundary) or not paths.is_within(p, boundary) or p == boundary:
                    return Decision("deny", f"recursive delete of {a!r} outside or at the root of {boundary}", "rm-outside")

    own_state = paths.state_dir(root) if root else None
    for p in touched + targets:
        st = _state_root_of(p)
        if st is None:
            continue
        if own_state is not None and paths.is_within(p, own_state):
            continue
        if paths.is_within(p, paths.ra_home()):
            continue
        return Decision("deny", f"{p} belongs to another Research-Agent project; projects are isolated", "cross-project")

    if agent_name == "reviewer" and root:
        scope = [root / s for s in _reviewer_scope()]
        for t in targets:
            if not _within_any(t, scope):
                return Decision("deny", f"the reviewer may only write under {', '.join(_reviewer_scope())}", "reviewer-scope")

    # ---- ask (Research-Agent projects only) ----------------------------------------------------------------------
    if root is None:
        return ALLOW
    asks: list[tuple[str, str, str]] = []  # (rule, target, reason)
    for p in touched:
        hit = _within_any(p, sensitive)
        if hit:
            asks.append(("phi-read", str(hit.relative_to(root)).replace("\\", "/"), f"access to sensitive data {p}"))
            break

    rate = float(config.get(cfg, "budget.gpu_usd_per_hour", 0) or 0)
    cap = float(config.get(cfg, "budget.max_gpu_usd_per_job", 0) or 0)
    level = config.get(cfg, "autonomy.level", "semi")
    prot_strings = [str(p) for p in protected] + [str(p) for p in config.get(cfg, "data.protected_paths", [])] if root else []
    for s in segs:
        if not s:
            continue
        v = shellparse.verb(s)
        text = " ".join(s)
        if (v == "git" and _git_subcommand(s) == "push") or (v == "gh" and len(s) > 2 and (s[1], s[2]) in {("pr", "create"), ("pr", "merge")}) \
                or (v == "gh" and len(s) > 1 and s[1] == "release") or (v == "twine" and "upload" in s) \
                or (v in ("npm", "poetry", "uv", "cargo") and "publish" in s) \
                or (("arxiv" in text.lower() or "openreview" in text.lower()) and re.search(r"\bsubmit\b", text.lower())) \
                or ("overleaf" in text.lower() and re.search(r"\bpush\b", text.lower())):
            asks.append(("publish", text, "publishes or pushes outside this machine"))
        if v in ("vastai", "sbatch", "qsub", "runpodctl", "srun") or (v == "modal" and len(s) > 1 and s[1] in ("run", "deploy", "launch", "serve")):
            asks.append(("cloud-gpu", text, "starts paid cloud or cluster compute"))
        if (v == "curl" and any(t in ("-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "-F", "--form", "-T", "--upload-file") or t.startswith("--data") for t in s)
                or v == "curl" and (_flag_value(s, "-X") or _flag_value(s, "--request") or "").upper() in ("POST", "PUT", "PATCH", "DELETE")) \
                or (v == "wget" and any(t.startswith(("--post-data", "--post-file", "--method")) for t in s)) \
                or v in ("scp", "sftp") or (v == "rsync" and any(shellparse.is_remote(a) for a in shellparse._args(s))):
            asks.append(("network-send", text, "sends data to another machine"))
        if _is_ra(s, "job", "run"):
            hours = _flag_value(s, "--gpu-hours")
            try:
                h = float(hours) if hours is not None else 0.0
            except ValueError:
                h = 0.0
            if h * rate > cap:
                asks.append(("gpu-over-cap", f"gpu-hours={h:g}", f"estimated ${h * rate:.2f} exceeds max_gpu_usd_per_job ${cap:.2f}"))
            elif level == "supervised":
                asks.append(("supervised-job", f"gpu-hours={h:g}", "supervised mode: every experiment launch needs approval"))
        if _is_ra(s, "kb", "promote") and "--approved" not in s:
            asks.append(("kb-promote", text, "promotes project knowledge to the global knowledge base"))
        if v in INTERPRETERS and any(t in ("-c", "-e", "-") for t in s) and any(ps and ps in cmd for ps in prot_strings):
            asks.append(("inline-protected", text, "inline script mentions protected raw data"))
        if level == "supervised" and (v in ("pip", "pip3", "conda", "mamba", "uv") and "install" in s or "pip" in s and "install" in s):
            asks.append(("supervised-install", text, "supervised mode: installing packages needs approval"))

    for rule, target, reason in asks:
        if approvals is not None and approvals.is_approved(rule, target):
            continue
        return Decision("ask", reason, rule)
    return ALLOW
