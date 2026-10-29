"""Machine setup (once per machine) and project initialisation (once per project)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import paths
from .skill_registry import _installed_plugins

GITIGNORE_LINES = [".research-agent/runs/*/pip_freeze.txt", ".research-agent/sessions/", ".research-agent/kb/.index.sqlite"]
PROJECT_DIRS = ("plans", "tasks", "artifacts", "runs", "reviews", "approvals", "kb/papers", "kb/notes", "memory", "checkpoints")
USER_CONFIG = """# Research-Agent machine-level overrides of config/default.toml (in the plugin).
# Projects override these again in <project>/.research-agent/project.toml.

# [budget]
# max_usd_per_session = 10.0
# max_usd_per_project = 100.0
# max_gpu_usd_per_job = 5.0
# gpu_usd_per_hour = 1.5

# [reviewer]
# backend = "claude"   # or "codex" after `/aris:setup`
"""


def aris_root(claude_home: Path | None = None) -> Path | None:
    for pid, path in _installed_plugins(Path(claude_home or paths.claude_home())):
        if pid.split("@", 1)[0] == "aris":
            return Path(path)
    return None


def setup_machine(reviewer: str = "claude", runner=subprocess.run) -> list[str]:
    actions: list[str] = []
    home = paths.ra_home()
    for d in (home / "knowledge" / "papers", home / "knowledge" / "notes"):
        d.mkdir(parents=True, exist_ok=True)
    bib = home / "knowledge" / "library.bib"
    if not bib.exists():
        bib.write_text("", encoding="utf-8")
    cfg = home / "config.toml"
    if not cfg.exists():
        cfg.write_text(USER_CONFIG, encoding="utf-8")
        actions.append(f"created {cfg}")

    aris = aris_root()
    if aris is None:
        actions.append("ARIS plugin not installed: skipped ~/.aris/repo and reviewer registration")
        return actions
    pointer = Path.home() / ".aris" / "repo"
    current = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
    if not current or not Path(current).is_dir():
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(str(aris) + "\n", encoding="utf-8")
        actions.append(f"wrote {pointer} -> {aris} (ARIS helper scripts)")

    if reviewer == "claude":
        server = aris / "mcp-servers" / "claude-review" / "server.py"
        listed = runner(["claude", "mcp", "list"], capture_output=True, text=True)
        if "claude-review" not in (listed.stdout or ""):
            runner(["claude", "mcp", "add", "claude-review", "-s", "user", "--", sys.executable, str(server)], capture_output=True, text=True)
            actions.append("registered claude-review MCP (fresh-context Claude reviewer for ARIS and the Reviewer agent)")
    else:
        actions.append("codex reviewer: install the Codex CLI (`npm install -g @openai/codex`), run `codex login`, "
                       "then run `/aris:setup` once inside Claude Code and restart it")
    return actions


def init_project(path: Path, protected, sensitive, irb: str = "", budget_session: float = 10.0,
                 budget_project: float = 100.0, reviewer: str = "claude") -> Path:
    path = Path(path).resolve()
    state = paths.state_dir(path)
    for d in PROJECT_DIRS:
        (state / d).mkdir(parents=True, exist_ok=True)
    toml = state / "project.toml"
    if not toml.exists():
        tpl = (paths.plugin_root() / "config" / "project.template.toml").read_text(encoding="utf-8")
        toml.write_text(tpl.format(name=path.name, irb=irb, protected=json.dumps(list(protected)), sensitive=json.dumps(list(sensitive)),
                                   budget_session=float(budget_session), budget_project=float(budget_project)), encoding="utf-8")
    if reviewer == "claude":
        rj = path / ".aris" / "reviewer.json"
        if not rj.exists():
            rj.parent.mkdir(parents=True, exist_ok=True)
            rj.write_text(json.dumps({"backend": "claude-review"}) + "\n", encoding="utf-8")
    gi = path / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    missing = [l for l in GITIGNORE_LINES if l not in existing.splitlines()]
    if missing:
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(("" if not existing or existing.endswith("\n") else "\n") + "\n".join(missing) + "\n")
    return state
