#!/usr/bin/env python3
"""Research-Agent installer (once per machine, user level). Ubuntu, macOS and Windows; stdlib only.

Each upstream skill repo is installed the way its own README says, never through Research-Agent's marketplace:
  superpowers        claude plugin install superpowers@claude-plugins-official
  ARIS               claude plugin marketplace add wanshuiyin/Auto-claude-code-research-in-sleep; install aris@aris
  humanizer          claude plugin marketplace add blader/humanizer; install humanizer@humanizer
  Supervisor-Skills  npx skills add HKUSTDial/Supervisor-Skills --global --agent claude-code   (-> ~/.claude/skills)
Then the plugin files of this checkout are staged into ~/.research-agent/plugin, added as the `research-agent`
marketplace, and research-agent@research-agent is installed.

Usage:  python3 install.py [--dry-run] [--yes] [--reviewer claude|codex] [--with-latex] [--with-drawio] [--extras PKG ...]
        Windows: py -3 install.py ...
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent
SUPERVISOR_SKILLS = (
    "idea-evaluator", "deep-research", "vibe-research-workflow", "tech-paper-template", "benchmark-paper-template",
    "intro-drafter", "paper-writer", "paper-polish", "pre-submission-reviewer", "figure-designer",
    "drawio-reconstruction", "rebuttal-guidance",
)
# What Claude Code needs from this checkout. Staged into ~/.research-agent/plugin so that a development checkout's
# .venv, .git, caches and tests are not copied into Claude Code's plugin cache.
PLUGIN_FILES = (".claude-plugin", "agents", "commands", "hooks", "bin", "config", "registry", "src", "docs",
                "README.md", "LICENSE", "pyproject.toml", "requirements-skills.txt")
NPX_SUPERVISOR = ["npx", "-y", "skills", "add", "HKUSTDial/Supervisor-Skills", "--global", "--agent", "claude-code",
                  "--skill", "*", "--yes", "--copy"]


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def ra_home() -> Path:
    return Path(os.environ.get("RA_HOME") or Path.home() / ".research-agent")


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def detect_state(home: Path | None = None) -> dict:
    home = Path(home or claude_home())
    skills = home / "skills"
    known = _json(home / "plugins" / "known_marketplaces.json")
    return {
        "marketplace_paths": {k: (v.get("source") or {}).get("path") or v.get("installLocation", "")
                              for k, v in known.items() if isinstance(v, dict)},
        "plugins": set((_json(home / "plugins" / "installed_plugins.json").get("plugins") or {}).keys()),
        "marketplaces": set(known.keys()),
        "user_skills": {d.name for d in skills.iterdir() if (d / "SKILL.md").is_file()} if skills.is_dir() else set(),
        "has_npx": shutil.which("npx") is not None,
    }


@dataclass
class Step:
    name: str
    cmds: list | Callable  # list of argv lists, or a callable(runner) -> bool


class Runner:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def run(self, cmd: list[str], check: bool = True) -> bool:
        print("  $ " + " ".join(cmd))
        if self.dry_run:
            return True
        exe = shutil.which(cmd[0]) or cmd[0]  # resolves claude.cmd / npx.cmd on Windows
        r = subprocess.run([exe, *cmd[1:]])
        if r.returncode != 0:
            print(f"  ! command failed with exit code {r.returncode}")
        return r.returncode == 0


# ---- steps ---------------------------------------------------------------------------------------------------------
def _plugin(state: dict, plugin_id: str, marketplace: str, source: str | None) -> list[list[str]]:
    if plugin_id in state["plugins"]:
        return []
    out = []
    if source and marketplace not in state["marketplaces"]:
        out.append(["claude", "plugin", "marketplace", "add", source])
    out.append(["claude", "plugin", "install", plugin_id, "--scope", "user"])
    return out


def stage_plugin(src: Path, dest: Path) -> None:
    """Copy only the plugin's own files into dest (replacing what was there)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", ".pytest_cache")
    for name in PLUGIN_FILES:
        p = Path(src) / name
        if p.is_dir():
            shutil.copytree(p, dest / name, ignore=ignore)
        elif p.is_file():
            shutil.copy2(p, dest / name)


def plugin_stage_dir() -> Path:
    return ra_home() / "plugin"


def research_agent_cmds(state: dict, stage: Path) -> list[list[str]]:
    pid, install_cmd = "research-agent@research-agent", ["claude", "plugin", "install", "research-agent@research-agent", "--scope", "user"]
    add = ["claude", "plugin", "marketplace", "add", str(stage)]
    registered = state.get("marketplace_paths", {}).get("research-agent")
    if "research-agent" not in state["marketplaces"]:
        return [add, install_cmd]
    if registered and Path(registered) != Path(stage):
        out = [["claude", "plugin", "uninstall", pid, "--scope", "user"]] if pid in state["plugins"] else []
        return out + [["claude", "plugin", "marketplace", "remove", "research-agent"], add, install_cmd]
    if pid not in state["plugins"]:
        return [install_cmd]
    return [["claude", "plugin", "marketplace", "update", "research-agent"], ["claude", "plugin", "update", pid, "--scope", "user"]]


def _research_agent_step(state: dict, repo: Path) -> Callable[["Runner"], bool]:
    def run(runner: "Runner") -> bool:
        stage = plugin_stage_dir()
        print(f"  stage plugin files: {repo} -> {stage}")
        if not runner.dry_run:
            stage_plugin(repo, stage)
        return all([runner.run(c) for c in research_agent_cmds(state, stage)])
    return run


def copy_supervisor_skills(src_repo: Path, dest: Path, force: bool) -> tuple[list[str], list[str]]:
    copied, skipped = [], []
    dest.mkdir(parents=True, exist_ok=True)
    for d in sorted((Path(src_repo) / "skills").iterdir()):
        if not (d / "SKILL.md").is_file():
            continue
        target = dest / d.name
        if target.exists() and not force:
            skipped.append(d.name)
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(d, target)
        copied.append(d.name)
    return copied, skipped


def _supervisor_fallback(force: bool) -> Callable[[Runner], bool]:
    def run(runner: Runner) -> bool:
        print("  copy route: git clone HKUSTDial/Supervisor-Skills, copy skills/* into ~/.claude/skills (existing dirs kept)")
        if runner.dry_run:
            return True
        with tempfile.TemporaryDirectory() as tmp:
            if not runner.run(["git", "clone", "--depth", "1", "https://github.com/HKUSTDial/Supervisor-Skills.git", tmp + "/repo"]):
                return False
            sha = subprocess.run(["git", "-C", tmp + "/repo", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            copied, skipped = copy_supervisor_skills(Path(tmp) / "repo", claude_home() / "skills", force)
        manifest = ra_home() / "installed" / "supervisor-skills.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"sha": sha, "copied": copied, "skipped": skipped}, indent=2), encoding="utf-8")
        print(f"  copied {len(copied)} skill(s)" + (f"; kept existing: {skipped} (use --force to overwrite)" if skipped else ""))
        return True
    return run


def _venv_python() -> Path:
    v = ra_home() / "venv"
    return v / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _home_step(reviewer: str) -> Callable[[Runner], bool]:
    def run(runner: Runner) -> bool:
        py = _venv_python()
        ok = True
        if not py.exists():
            ok &= runner.run([sys.executable, "-m", "venv", str(ra_home() / "venv")])
        ok &= runner.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        ok &= runner.run([str(py), "-m", "pip", "install", "-q", "-r", str(REPO / "requirements-skills.txt")])
        ok &= runner.run([str(py), "-m", "pip", "install", "-q", "-e", str(REPO)])
        ok &= runner.run([str(py), "-m", "research_agent", "setup", "--reviewer", reviewer])
        return ok
    return run


def _extras_step(o) -> Callable[[Runner], bool]:
    def run(runner: Runner) -> bool:
        ok = True
        if o.with_latex:
            if sys.platform.startswith("linux") and shutil.which("apt-get"):
                pre = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
                ok &= runner.run(pre + ["apt-get", "install", "-y", "texlive-latex-extra", "texlive-fonts-recommended",
                                        "texlive-bibtex-extra", "latexmk", "biber", "poppler-utils"])
            elif os.name == "nt":
                print("  LaTeX on Windows: `winget install MiKTeX.MiKTeX` (then enable on-the-fly package install) and Strawberry Perl for latexmk")
            else:
                print("  LaTeX: install TeX Live (macOS: `brew install --cask mactex-no-gui`)")
        if o.with_drawio:
            print("  draw.io: install the desktop app (https://github.com/jgraph/drawio-desktop/releases); on headless Linux also `apt-get install xvfb`")
        if o.extras:
            ok &= runner.run([str(_venv_python()), "-m", "pip", "install", "-q", *o.extras])
        return ok
    return run


def _preflight(runner: Runner) -> bool:
    ok = sys.version_info >= (3, 11)
    print(f"  python {platform.python_version()} {'ok' if ok else '(need >= 3.11)'}")
    for tool, required in (("claude", True), ("git", True), ("npx", False)):
        found = shutil.which(tool)
        print(f"  {tool}: {found or ('MISSING' if required else 'not found (Supervisor-Skills will use the git copy route)')}")
        ok &= bool(found) or not required
    return ok


def plan_steps(state: dict, o, confirm: Callable[[str], bool]) -> list[Step]:
    steps = [Step("preflight", _preflight)]
    tutu = sorted(p for p in state["plugins"] if p.endswith("@tutu"))
    if (tutu or "tutu" in state["marketplaces"]) and not o.skip_migrate:
        msg = (f"Found the old Tutu install ({', '.join(tutu) or 'tutu marketplace'}). It bundles the four skill repos inside "
               "Tutu's own plugin cache. Uninstall it and reinstall the repos from their upstream sources?")
        if o.yes or confirm(msg):
            cmds = [["claude", "plugin", "uninstall", p, "--scope", "user"] for p in tutu]
            if "tutu" in state["marketplaces"]:
                cmds.append(["claude", "plugin", "marketplace", "remove", "tutu"])
            steps.append(Step("migrate-tutu", cmds))
            state = {**state, "plugins": state["plugins"] - set(tutu), "marketplaces": state["marketplaces"] - {"tutu"}}
    steps.append(Step("superpowers", _plugin(state, "superpowers@claude-plugins-official", "claude-plugins-official",
                                             "anthropics/claude-plugins-official")))
    steps.append(Step("aris", _plugin(state, "aris@aris", "aris", "wanshuiyin/Auto-claude-code-research-in-sleep")))
    steps.append(Step("humanizer", _plugin(state, "humanizer@humanizer", "humanizer", "blader/humanizer")))
    present = set(SUPERVISOR_SKILLS) & state["user_skills"]
    if present == set(SUPERVISOR_SKILLS) and not o.force:
        steps.append(Step("supervisor-skills", []))
    elif state["has_npx"] and (not present or o.force):
        steps.append(Step("supervisor-skills", [NPX_SUPERVISOR]))
    else:
        steps.append(Step("supervisor-skills", _supervisor_fallback(o.force)))
    steps.append(Step("research-agent", _research_agent_step(state, Path(o.repo))))
    steps.append(Step("home", _home_step(o.reviewer)))
    if o.with_latex or o.with_drawio or o.extras:
        steps.append(Step("extras", _extras_step(o)))
    steps.append(Step("doctor", lambda r: r.run([str(_venv_python()), "-m", "research_agent", "doctor", "--skills"], check=False) or True))
    return steps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install Research-Agent and its skill repos (user level).")
    ap.add_argument("--dry-run", action="store_true", help="print what would be done, change nothing")
    ap.add_argument("--yes", action="store_true", help="answer yes to the Tutu migration prompt")
    ap.add_argument("--skip-migrate", action="store_true", help="leave an old Tutu install alone")
    ap.add_argument("--force", action="store_true", help="overwrite existing Supervisor-Skills directories")
    ap.add_argument("--reviewer", choices=["claude", "codex"], default="claude")
    ap.add_argument("--with-latex", action="store_true")
    ap.add_argument("--with-drawio", action="store_true")
    ap.add_argument("--extras", nargs="*", default=[])
    o = ap.parse_args(argv)
    o.repo = REPO

    def confirm(msg: str) -> bool:
        return input(f"{msg} [y/N] ").strip().lower() in ("y", "yes")

    runner = Runner(dry_run=o.dry_run)
    failed = []
    for step in plan_steps(detect_state(), o, confirm):
        print(f"[{step.name}]")
        if isinstance(step.cmds, list):
            if not step.cmds:
                print("  already installed")
            ok = all([runner.run(c) for c in step.cmds])
        else:
            ok = step.cmds(runner)
        if not ok:
            failed.append(step.name)
            if step.name == "preflight":
                print("Preflight failed; install the missing tools and re-run.")
                return 1
    if failed:
        print(f"\nFinished with failures in: {', '.join(failed)}. Fix them and re-run (completed steps are skipped).")
        return 1
    print("\nDone. Restart Claude Code, then in any project run /research-agent:ra-init and /research-agent:ra <goal>.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
