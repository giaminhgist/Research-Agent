"""`ra doctor`: is this machine set up the way Research-Agent expects?"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from . import paths
from .agent_factory import build_all
from .agent_registry import load_agents
from .skill_registry import SkillRegistry, installed_plugin_ids

REQUIRED_PLUGINS = ("superpowers@claude-plugins-official", "aris@aris", "humanizer@humanizer", "research-agent@research-agent")
EXPECTED_COUNTS = {"superpowers": 15, "aris": 87, "supervisor-skills": 12, "humanizer": 1}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    level: str = "error"


def run(skills: bool = False, live: bool = False) -> list[Check]:
    out = [Check("python>=3.11", sys.version_info >= (3, 11), sys.version.split()[0]),
           Check("claude CLI", shutil.which("claude") is not None, shutil.which("claude") or "not on PATH")]
    ids = installed_plugin_ids()
    for pid in REQUIRED_PLUGINS:
        out.append(Check(f"plugin {pid}", pid in ids, "installed" if pid in ids else f"missing: run install.py"))
    tutu = [i for i in ids if i.endswith("@tutu")]
    out.append(Check("no-tutu", not tutu, f"old Tutu plugins still installed: {tutu} (run install.py to migrate)" if tutu else "none"))
    stale = build_all(paths.plugin_root() / "agents", check=True)
    out.append(Check("agents in sync", not stale, f"regenerate with `ra agents build`: {stale}" if stale else "ok"))

    if skills or live:
        reg = SkillRegistry.discover()
        counts = reg.counts_by_source()
        for repo, n in EXPECTED_COUNTS.items():
            got = counts.get(repo, 0)
            out.append(Check(f"skills {repo}", got >= n, f"{got} installed (expected {n})", "error" if got == 0 else "warn"))
        for agent in load_agents().values():
            missing = [s for s in agent.core_skills if not (reg.get(s) and reg.get(s).installed)]
            out.append(Check(f"preload {agent.name}", not missing, f"not installed: {missing}" if missing else f"{len(agent.core_skills)} core skills"))
            unavailable = []
            for sid in agent.core_skills + agent.borrow_skills:
                ok, why = reg.available(sid)
                if not ok and "not installed" not in why:
                    unavailable.append(f"{sid} ({', '.join(why)})")
            if unavailable:
                out.append(Check(f"optional {agent.name}", False, "needs keys/tools: " + "; ".join(unavailable), "warn"))
        try:
            listed = subprocess.run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=120).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            listed = str(exc)
        line = next((l for l in listed.splitlines() if l.startswith("claude-review") or l.startswith("codex")), "")
        out.append(Check("reviewer MCP", bool(line), line or "neither claude-review nor codex is registered (run `ra setup`)"))
        if live:
            out.append(Check("reviewer MCP connected", "Connected" in line or "✓" in line, line or "not registered"))
    return out
