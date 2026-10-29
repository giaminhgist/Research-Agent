"""Claude Code hook handlers. `hooks/dispatch.py <Event>` feeds the JSON payload to `handle`.

Every handler is a no-op outside a Research-Agent project, except the universal guard deny rules.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from . import config, guard, kb, paths
from .approvals import ApprovalStore
from .budget import Budget, session_cost_from_transcript
from .memory import ProjectMemory

DISPATCH_TOOLS = {"Agent", "Task"}
PROMOTION_AGENTS = {"research", "methodology", "reviewer"}
TRAIN_RE = re.compile(r"\bpython[0-9.]*(\.exe)?\s+(-m\s+)?\S*(train|eval|fit|finetune|experiment)\w*", re.I)


def _pre(decision: str | None = None, reason: str = "", context: str = "") -> dict:
    out: dict = {"hookEventName": "PreToolUse"}
    if decision:
        out["permissionDecision"] = decision
        out["permissionDecisionReason"] = reason
    if context:
        out["additionalContext"] = context
    return {"hookSpecificOutput": out}


def _session_file(project: Path, session_id: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", session_id or "unknown")
    return paths.state_dir(project) / "sessions" / f"{safe}.json"


def _pre_tool(payload: dict, cwd: Path, project: Path | None) -> dict | None:
    tool = payload.get("tool_name", "")
    cfg = config.load(project)
    warn = ""
    if project and tool in DISPATCH_TOOLS:
        sid = str(payload.get("session_id", ""))
        cost = session_cost_from_transcript(Path(payload["transcript_path"]), cfg.get("pricing", {})) if payload.get("transcript_path") else None
        action, msg = Budget(project, cfg).check_dispatch(sid, cost)
        if action == "deny":
            return _pre("deny", f"[research-agent:budget] {msg}. Stop dispatching and report to the user: only the user may raise "
                                "the cap (.research-agent/project.toml). Do not edit budget or config files yourself.")
        sf = _session_file(project, sid)
        try:
            count = json.loads(sf.read_text(encoding="utf-8")).get("dispatches", 0)
        except (OSError, ValueError):
            count = 0
        cap = int(config.get(cfg, "budget.max_subagents_per_session", 0) or 0)
        if cap and count >= cap:
            return _pre("deny", f"[research-agent:budget] {count} subagents already dispatched this session (max_subagents_per_session={cap}).")
        if action == "warn":
            warn = f"Research-Agent budget warning: {msg}."
    d = guard.evaluate(tool, payload.get("tool_input") or {}, cwd, cfg, project, agent=payload.get("agent_type"),
                       approvals=ApprovalStore(project) if project else None)
    if d.action != "allow":
        return _pre(d.action, f"[research-agent:{d.rule}] {d.reason}")
    if project and tool in DISPATCH_TOOLS:
        sf = _session_file(project, str(payload.get("session_id", "")))
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps({"dispatches": count + 1}), encoding="utf-8")
    return _pre(context=warn) if warn else None


def _post_tool(payload: dict, project: Path) -> dict | None:
    if payload.get("tool_name") != "Bash":
        return None
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if TRAIN_RE.search(cmd) and "ra job run" not in cmd and "research_agent job run" not in cmd:
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
            "Research-Agent: this looks like a training/evaluation run started without provenance. Results count only "
            "with a run_id: re-run it as `ra job run [--gpu-hours H] --seed S --config F -- <command>`.")}}
    return None


def to_bash_path(p) -> str:
    """Path as Git Bash / MSYS expects it: C:\\Users\\x -> /c/Users/x (POSIX paths unchanged)."""
    s = str(p).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    return f"/{m.group(1).lower()}/{m.group(2)}" if m else s


def _export_path(env: Mapping) -> None:
    env_file = env.get("CLAUDE_ENV_FILE")
    if not env_file:
        return
    bins = [paths.ra_home() / "venv" / ("Scripts" if sys.platform == "win32" else "bin"), paths.plugin_root() / "bin"]
    with open(env_file, "a", encoding="utf-8") as fh:
        fh.write("export PATH=\"" + ":".join(to_bash_path(b) for b in bins) + ":$PATH\"\n")


def _session_start(project: Path) -> dict:
    cfg = config.load(project)
    parts = [f"Research-Agent project: {project} (plugin: {paths.plugin_root()}). Use `ra status` for details."]
    mem = ProjectMemory(project).summary(1200)
    if mem:
        parts.append(mem)
    pending = ApprovalStore(project).pending()
    if pending:
        parts.append(f"Pending approvals: {len(pending)} (`ra approve list`).")
    s = Budget(project, cfg).summary()
    parts.append(f"Budget: project ${s['project_usd']:.2f} of ${s['caps']['max_usd_per_project']:.2f}; "
                 f"session cap ${s['caps']['max_usd_per_session']:.2f}; GPU job cap ${s['caps']['max_gpu_usd_per_job']:.2f}.")
    q = kb.list_queue(project)
    if q:
        parts.append(f"{len(q)} knowledge items await a global-KB decision (`ra kb queue`); ask the user.")
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(parts)}}


def _subagent_stop(payload: dict, project: Path) -> dict | None:
    agent = str(payload.get("agent_type") or "").split(":")[-1]
    if agent and agent not in PROMOTION_AGENTS:
        return None
    new = kb.queue_candidates(project, since=kb.last_scan(project), origin_agent=agent or None)
    if not new:
        return None
    n = len(new)
    return {"systemMessage": f"Research-Agent: {n} knowledge item{'s' if n > 1 else ''} queued for the global knowledge base. "
                             "The orchestrator must ask the user which to promote (`ra kb queue`)."}


def _record_cost(payload: dict, project: Path) -> None:
    t = payload.get("transcript_path")
    if not t:
        return
    cfg = config.load(project)
    cost = session_cost_from_transcript(Path(t), cfg.get("pricing", {}))
    if cost is not None:
        Budget(project, cfg).record_session(str(payload.get("session_id", "unknown")), cost)


def handle(event: str, payload: dict, env: Mapping | None = None) -> dict | None:
    env = os.environ if env is None else env
    cwd = Path(payload.get("cwd") or os.getcwd())
    project = paths.find_project_root(cwd)
    if event == "PreToolUse":
        return _pre_tool(payload, cwd, project)
    if event == "SessionStart":
        _export_path(env)
    if project is None:
        return None
    if event == "PostToolUse":
        return _post_tool(payload, project)
    if event == "SessionStart":
        return _session_start(project)
    if event == "SubagentStop":
        return _subagent_stop(payload, project)
    if event in ("Stop", "SessionEnd"):
        _record_cost(payload, project)
    return None
