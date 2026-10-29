import importlib.util
import subprocess
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ra_install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
import sys
sys.modules["ra_install"] = install
spec.loader.exec_module(install)

TUTU = {"tutu@tutu", "superpowers@tutu", "aris@tutu", "humanizer@tutu", "supervisor-skills@tutu"}


def opts(**kw):
    base = dict(yes=False, skip_migrate=False, force=False, reviewer="claude", with_latex=False, with_drawio=False, extras=[], repo=ROOT)
    return types.SimpleNamespace(**{**base, **kw})


def cmds(steps, name):
    step = next(s for s in steps if s.name == name)
    return step.cmds if isinstance(step.cmds, list) else "callable"


def state(**kw):
    base = dict(plugins=set(), marketplaces={"claude-plugins-official"}, user_skills=set(), has_npx=True, marketplace_paths={})
    return {**base, **kw}


def test_fresh_machine_commands():
    steps = install.plan_steps(state(), opts(), confirm=lambda m: True)
    assert cmds(steps, "superpowers") == [["claude", "plugin", "install", "superpowers@claude-plugins-official", "--scope", "user"]]
    assert cmds(steps, "aris") == [["claude", "plugin", "marketplace", "add", "wanshuiyin/Auto-claude-code-research-in-sleep"],
                                   ["claude", "plugin", "install", "aris@aris", "--scope", "user"]]
    assert cmds(steps, "humanizer") == [["claude", "plugin", "marketplace", "add", "blader/humanizer"],
                                        ["claude", "plugin", "install", "humanizer@humanizer", "--scope", "user"]]
    assert cmds(steps, "supervisor-skills") == [["npx", "-y", "skills", "add", "HKUSTDial/Supervisor-Skills", "--global",
                                                 "--agent", "claude-code", "--skill", "*", "--yes", "--copy"]]
    assert cmds(steps, "research-agent") == "callable"
    assert "migrate-tutu" not in [s.name for s in steps]
    flat = [" ".join(c) for s in steps if isinstance(s.cmds, list) for c in s.cmds]
    assert not any("@tutu" in c or "@research-agent" in c and "research-agent@research-agent" not in c for c in flat)


def test_official_marketplace_added_when_missing():
    steps = install.plan_steps(state(marketplaces=set()), opts(), confirm=lambda m: True)
    assert cmds(steps, "superpowers")[0] == ["claude", "plugin", "marketplace", "add", "anthropics/claude-plugins-official"]


def test_tutu_migration_commands_when_present():
    steps = install.plan_steps(state(plugins=set(TUTU), marketplaces={"tutu", "claude-plugins-official"}), opts(), confirm=lambda m: True)
    mig = cmds(steps, "migrate-tutu")
    assert sorted(mig[:-1]) == sorted(["claude", "plugin", "uninstall", p, "--scope", "user"] for p in TUTU)
    assert mig[-1] == ["claude", "plugin", "marketplace", "remove", "tutu"]
    assert [s.name for s in steps].index("migrate-tutu") < [s.name for s in steps].index("superpowers")


def test_migration_skipped_without_confirmation():
    asked = []
    steps = install.plan_steps(state(plugins=set(TUTU), marketplaces={"tutu"}), opts(), confirm=lambda m: asked.append(m) or False)
    assert asked and "tutu" in asked[0].lower()
    assert "migrate-tutu" not in [s.name for s in steps]
    assert "superpowers" in [s.name for s in steps]


def test_skip_migrate_flag_does_not_ask():
    steps = install.plan_steps(state(plugins=set(TUTU)), opts(skip_migrate=True), confirm=lambda m: pytest.fail("asked"))
    assert "migrate-tutu" not in [s.name for s in steps]


def test_idempotent_rerun_emits_nothing_for_installed():
    full = state(plugins={"superpowers@claude-plugins-official", "aris@aris", "humanizer@humanizer", "research-agent@research-agent"},
                 marketplaces={"claude-plugins-official", "aris", "humanizer", "research-agent"},
                 user_skills=set(install.SUPERVISOR_SKILLS))
    steps = install.plan_steps(full, opts(), confirm=lambda m: pytest.fail("asked"))
    for name in ("superpowers", "aris", "humanizer", "supervisor-skills"):
        assert cmds(steps, name) == [], name


def test_partial_supervisor_install_uses_copy_fallback():
    steps = install.plan_steps(state(user_skills={"deep-research"}), opts(), confirm=lambda m: True)
    assert cmds(steps, "supervisor-skills") == "callable"
    steps = install.plan_steps(state(user_skills={"deep-research"}), opts(force=True), confirm=lambda m: True)
    assert cmds(steps, "supervisor-skills")[0][:4] == ["npx", "-y", "skills", "add"]


def test_no_npx_uses_copy_fallback():
    assert cmds(install.plan_steps(state(has_npx=False), opts(), confirm=lambda m: True), "supervisor-skills") == "callable"


def test_supervisor_fallback_copy_skips_collisions(tmp_path):
    src = tmp_path / "clone"
    for n in install.SUPERVISOR_SKILLS:
        (src / "skills" / n).mkdir(parents=True)
        (src / "skills" / n / "SKILL.md").write_text(f"---\nname: {n}\n---\n")
    (src / "skills" / "not-a-skill").mkdir()
    dest = tmp_path / "skills"
    (dest / "deep-research").mkdir(parents=True)
    (dest / "deep-research" / "SKILL.md").write_text("mine")
    copied, skipped = install.copy_supervisor_skills(src, dest, force=False)
    assert len(copied) == 11 and skipped == ["deep-research"]
    assert (dest / "deep-research" / "SKILL.md").read_text() == "mine"
    copied, skipped = install.copy_supervisor_skills(src, dest, force=True)
    assert len(copied) == 12 and (dest / "deep-research" / "SKILL.md").read_text() != "mine"


def test_detect_state(tmp_path, monkeypatch):
    from fixtures_claude import make_claude_home
    home = make_claude_home(tmp_path)
    (home / "plugins" / "known_marketplaces.json").write_text('{"aris": {}, "tutu": {}}')
    (home / "plugins" / "known_marketplaces.json").write_text('{"aris": {}, "tutu": {}, "research-agent": {"source": {"source": "directory", "path": "/x"}}}')
    st = install.detect_state(home)
    assert "aris@aris" in st["plugins"] and st["marketplaces"] == {"aris", "tutu", "research-agent"}
    assert st["marketplace_paths"]["research-agent"] == "/x"
    assert {"deep-research", "my-own-skill"} <= st["user_skills"]


def test_dry_run_executes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("RA_HOME", str(tmp_path / "ra"))

    def boom(*a, **k):
        raise AssertionError(f"subprocess called: {a}")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(install.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert install.main(["--dry-run", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "claude plugin install aris@aris --scope user" in out and "skills add HKUSTDial/Supervisor-Skills" in out
    assert not (tmp_path / "ra").exists()


def test_stage_plugin_copies_only_plugin_files(tmp_path):
    src = tmp_path / "checkout"
    for rel in ("agents/a.md", "src/research_agent/x.py", ".claude-plugin/plugin.json", ".venv/bin/python",
                ".superpowers/sdd/x", "src/research_agent/__pycache__/x.pyc", ".git/HEAD", "tests/t.py", ".pytest_cache/x"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    dest = tmp_path / "stage"
    (dest / "stale.txt").parent.mkdir(parents=True)
    (dest / "stale.txt").write_text("old")
    install.stage_plugin(src, dest)
    got = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert got == [".claude-plugin/plugin.json", "agents/a.md", "src/research_agent/x.py"]


def test_research_agent_step_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("RA_HOME", str(tmp_path / "ra"))
    stage = tmp_path / "ra" / "plugin"
    fresh = install.research_agent_cmds(state(), stage)
    assert fresh == [["claude", "plugin", "marketplace", "add", str(stage)],
                     ["claude", "plugin", "install", "research-agent@research-agent", "--scope", "user"]]
    moved = install.research_agent_cmds(state(plugins={"research-agent@research-agent"}, marketplaces={"research-agent"},
                                              marketplace_paths={"research-agent": "/old/checkout"}), stage)
    assert moved == [["claude", "plugin", "uninstall", "research-agent@research-agent", "--scope", "user"],
                     ["claude", "plugin", "marketplace", "remove", "research-agent"],
                     ["claude", "plugin", "marketplace", "add", str(stage)],
                     ["claude", "plugin", "install", "research-agent@research-agent", "--scope", "user"]]
    same = install.research_agent_cmds(state(plugins={"research-agent@research-agent"}, marketplaces={"research-agent"},
                                             marketplace_paths={"research-agent": str(stage)}), stage)
    assert same == [["claude", "plugin", "marketplace", "update", "research-agent"],
                    ["claude", "plugin", "update", "research-agent@research-agent", "--scope", "user"]]
