"""Best-effort shell command analysis for the guard: segments, verbs and the paths a command writes."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

SEPARATORS = {";", "&&", "||", "|", "&", "|&"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "nice", "exec", "xargs"}


def _tokens(line: str) -> list[str]:
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return line.split()


def segments(cmd: str) -> list[list[str]]:
    out: list[list[str]] = []
    for line in cmd.replace("\\\n", " ").splitlines():
        cur: list[str] = []
        for t in _tokens(line):
            if t in SEPARATORS:
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            out.append(cur)
    return out


def strip_wrappers(seg: list[str]) -> list[str]:
    i = 0
    while i < len(seg) and ("=" in seg[i] and not seg[i].startswith("-") and seg[i].split("=", 1)[0].isidentifier() or seg[i] in WRAPPERS):
        i += 1
    return seg[i:]


def verb(seg: list[str]) -> str:
    s = strip_wrappers(seg)
    return os.path.basename(s[0]).lower().removesuffix(".exe") if s else ""


def resolve_path(arg: str, cwd: Path) -> Path:
    p = Path(os.path.expanduser(arg.replace("\\", "/")))
    if not p.is_absolute():
        p = Path(cwd) / p
    return Path(os.path.normpath(str(p)))


def _args(seg: list[str]) -> list[str]:
    """Non-option arguments, excluding redirect operators and their targets."""
    out, skip = [], False
    for t in seg[1:]:
        if skip:
            skip = False
            continue
        if t in REDIRECTS or t in {"<", "<<", "<<<", ">&", "<&"}:
            skip = True
            continue
        if t.startswith("-"):
            continue
        out.append(t)
    return out


def write_targets(cmd: str, cwd: Path) -> list[Path]:
    """Paths a command would create, modify or delete (best effort, tracks `cd`)."""
    cwd = Path(cwd)
    targets: list[Path] = []
    for seg in segments(cmd):
        for i, t in enumerate(seg[:-1]):
            nxt = seg[i + 1]
            if t in REDIRECTS and not nxt.startswith("&") and nxt != "/dev/null":
                targets.append(resolve_path(nxt, cwd))
        s = strip_wrappers(seg)
        if not s:
            continue
        v = verb(s)
        args = _args(s)
        if v == "cd":
            cwd = resolve_path(args[0], cwd) if args else Path.home()
        elif v == "tee":
            targets += [resolve_path(a, cwd) for a in args]
        elif v in {"cp", "rsync", "install", "ln"} and args:
            if not (v == "rsync" and _is_remote(args[-1])):
                targets.append(resolve_path(args[-1], cwd))
        elif v == "mv":
            targets += [resolve_path(a, cwd) for a in args]
        elif v in {"rm", "rmdir", "unlink", "truncate", "shred", "touch", "mkdir"}:
            targets += [resolve_path(a, cwd) for a in args]
        elif v == "sed" and any(t == "-i" or t.startswith("-i") or t == "--in-place" or t.startswith("--in-place=") for t in s[1:]):
            has_script_flag = any(t in ("-e", "-f", "--expression", "--file") for t in s[1:])
            files = args if has_script_flag else args[1:]
            targets += [resolve_path(a, cwd) for a in files]
        elif v == "dd":
            targets += [resolve_path(a[3:], cwd) for a in s[1:] if a.startswith("of=")]
    return targets


def _is_remote(arg: str) -> bool:
    head = arg.split(":", 1)[0]
    return ":" in arg and not arg.startswith("/") and len(head) > 1 and "/" not in head


def is_remote(arg: str) -> bool:
    return _is_remote(arg)
