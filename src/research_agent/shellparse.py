"""Best-effort shell command analysis for the guard.

`analyze(cmd, cwd)` walks the command segment by segment, tracking `cd`, recursing into `bash -c` / `sh -c` /
`eval`, and returns:
  exact  - paths a command creates, modifies or deletes;
  tree   - paths whose whole subtree a command can destroy or rewrite (rm -r, git clean/checkout/restore,
           find -delete, chmod -R, mv of a directory, xargs rm ...). A tree target that *contains* protected
           data is as dangerous as one inside it.
It cannot see what a script does internally or what `$VAR` expands to; see docs/SAFETY.md.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

SEPARATORS = {";", "&&", "||", "|", "&", "|&"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "nice", "exec"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
DESTRUCTIVE = {"rm", "mv", "shred", "unlink", "truncate", "chmod", "chown", "cp", "sed", "perl"}


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


def _flag_value(s: list[str], *flags: str) -> str | None:
    for i, t in enumerate(s):
        for f in flags:
            if t == f and i + 1 < len(s):
                return s[i + 1]
            if f.startswith("--") and t.startswith(f + "="):
                return t.split("=", 1)[1]
    return None


def _recursive(s: list[str]) -> bool:
    return any(t in ("-r", "-R", "--recursive", "-a", "--archive") or (t.startswith("-") and not t.startswith("--") and ("r" in t or "R" in t)) for t in s[1:])


def is_remote(arg: str) -> bool:
    head = arg.split(":", 1)[0]
    return ":" in arg and not arg.startswith("/") and len(head) > 1 and "/" not in head


def git_subcommand(s: list[str]) -> str:
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


@dataclass
class Analysis:
    exact: list[Path] = field(default_factory=list)
    tree: list[Path] = field(default_factory=list)
    segs: list[tuple[list[str], Path]] = field(default_factory=list)  # (stripped segment, cwd at that point)


def analyze(cmd: str, cwd: Path, _depth: int = 0) -> Analysis:
    a = Analysis()
    cwd = Path(cwd)
    prev: list[str] = []
    for raw in segments(cmd):
        for i, t in enumerate(raw[:-1]):
            nxt = raw[i + 1]
            if t in REDIRECTS and not nxt.startswith("&") and nxt != "/dev/null":
                a.exact.append(resolve_path(nxt, cwd))
        if raw and os.path.basename(raw[0]) == "xargs":
            inner = strip_wrappers(raw[1:])
            if inner and os.path.basename(inner[0]) in DESTRUCTIVE:
                a.tree += [resolve_path(x, cwd) for x in _args(prev)]
            raw = raw[1:]
        s = strip_wrappers(raw)
        prev = s
        if not s:
            continue
        a.segs.append((s, cwd))
        v = verb(s)
        args = _args(s)
        rp = lambda xs: [resolve_path(x, cwd) for x in xs]  # noqa: E731
        if v == "cd":
            cwd = resolve_path(args[0], cwd) if args else Path.home()
        elif v in SHELLS and "-c" in s and _depth < 3:
            inner = s[s.index("-c") + 1] if s.index("-c") + 1 < len(s) else ""
            sub = analyze(inner, cwd, _depth + 1)
            a.exact += sub.exact
            a.tree += sub.tree
            a.segs += sub.segs
        elif v == "eval" and _depth < 3:
            sub = analyze(" ".join(s[1:]), cwd, _depth + 1)
            a.exact += sub.exact
            a.tree += sub.tree
            a.segs += sub.segs
        elif v == "tee":
            a.exact += rp(args)
        elif v in {"cp", "rsync", "install", "ln"} and args:
            if not (v == "rsync" and is_remote(args[-1])):
                a.exact.append(resolve_path(args[-1], cwd))
        elif v == "mv":
            a.exact += rp(args)
            a.tree += rp(args)
        elif v in {"rm", "rmdir", "unlink", "truncate", "shred", "touch", "mkdir"}:
            a.exact += rp(args)
            if v == "rm" and _recursive(s):
                a.tree += rp(args)
        elif v in {"chmod", "chown", "chgrp"} and len(args) > 1:
            a.exact += rp(args[1:])
            if _recursive(s):
                a.tree += rp(args[1:])
        elif v == "sed" and any(t == "-i" or t.startswith("-i") or t == "--in-place" or t.startswith("--in-place=") for t in s[1:]):
            has_script_flag = any(t in ("-e", "-f", "--expression", "--file") for t in s[1:])
            a.exact += rp(args if has_script_flag else args[1:])
        elif v in {"perl", "ruby"} and any(t.startswith("-i") or (t.startswith("-") and not t.startswith("--") and "i" in t) for t in s[1:]):
            a.exact += rp(args[1:])
        elif v == "dd":
            a.exact += [resolve_path(x[3:], cwd) for x in s[1:] if x.startswith("of=")]
        elif v == "wget" and (o := _flag_value(s, "-O", "--output-document")):
            a.exact.append(resolve_path(o, cwd))
        elif v == "curl" and (o := _flag_value(s, "-o", "--output")):
            a.exact.append(resolve_path(o, cwd))
        elif v == "unzip" and (o := _flag_value(s, "-d")):
            a.exact.append(resolve_path(o, cwd))
        elif v == "tar" and (o := _flag_value(s, "-C", "--directory")) and any(
                t == "--extract" or (t.startswith("-") and not t.startswith("--") and "x" in t) or (not t.startswith("-") and "x" in t and i == 1)
                for i, t in enumerate(s[1:], 1)):
            a.exact.append(resolve_path(o, cwd))
        elif v == "find":
            roots = []
            for t in s[1:]:
                if t.startswith("-") or t in ("(", "!"):
                    break
                roots.append(t)
            execs = [s[i + 1] for i, t in enumerate(s[:-1]) if t in ("-exec", "-execdir", "-ok")]
            if "-delete" in s or any(os.path.basename(e) in DESTRUCTIVE for e in execs):
                a.tree += rp(roots or ["."])
        elif v == "git":
            sub = git_subcommand(s)
            rest = s[s.index(sub) + 1:] if sub in s else []
            paths = rest[rest.index("--") + 1:] if "--" in rest else [x for x in rest if not x.startswith("-")]
            if sub == "restore" or (sub == "checkout" and "--" in rest):
                a.tree += rp(paths or ["."])
            elif sub == "checkout":
                a.tree += [p for p in rp(paths) if p.exists()]
            elif sub == "clean":
                a.tree += rp(paths or ["."])
            elif sub == "stash" and any(t in ("-u", "--include-untracked", "-a", "--all") for t in rest):
                a.tree.append(cwd)
            elif sub == "reset" and "--hard" in rest:
                a.tree.append(cwd)
    return a


def write_targets(cmd: str, cwd: Path) -> list[Path]:
    """Paths a command would create, modify or delete (best effort)."""
    return analyze(cmd, cwd).exact
