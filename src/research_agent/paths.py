"""Filesystem locations used by Research-Agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

STATE_DIRNAME = ".research-agent"


def ra_home() -> Path:
    """Machine-level home (config, global knowledge base, venv)."""
    env = os.environ.get("RA_HOME")
    return Path(env) if env else Path.home() / ".research-agent"


def claude_home() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def state_dir(project: Path) -> Path:
    return Path(project) / STATE_DIRNAME


def _norm(p: Path) -> str:
    s = str(Path(os.path.abspath(Path(p).expanduser()))).replace("\\", "/")
    return s.lower() if sys.platform == "win32" else s


def is_within(p: Path, root: Path) -> bool:
    child, parent = _norm(Path(p).resolve()), _norm(Path(root).resolve())
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def find_project_root(start: Path) -> Path | None:
    """Nearest ancestor containing `.research-agent/`, never the home directory or above it."""
    home = Path.home().resolve()
    cur = Path(start).resolve()
    for d in (cur, *cur.parents):
        if d == home or is_within(home, d):
            return None
        if (d / STATE_DIRNAME).is_dir():
            return d
    return None
