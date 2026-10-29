import json
import sys
from pathlib import Path

import pytest

from fixtures_claude import make_claude_home
from research_agent import cli, doctor, sdk_runner, setup
from research_agent.approvals import ApprovalStore

ROOT = Path(__file__).resolve().parents[1]


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    return code, out


def test_cli_route_json(capsys):
    code, out = run(capsys, "route", "implement a GRU baseline in PyTorch", "--json")
    assert code == 0 and json.loads(out)["agent"] == "coding"


def test_cli_resolve_json(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(make_claude_home(tmp_path)))
    code, out = run(capsys, "resolve", "make conference slides", "--agent", "writing", "--json")
    data = json.loads(out)
    assert code == 0 and data["agent"] == "writing" and "preload" in data and "missing" in data


def test_init_idempotent(tmp_path, tmp_home):
    p = tmp_path / "study"
    p.mkdir()
    setup.init_project(p, protected=["data/raw"], sensitive=["data/phi"], irb="IRB-42", budget_session=5.0, budget_project=50.0)
    toml = (p / ".research-agent" / "project.toml").read_text()
    assert 'protected_paths = ["data/raw"]' in toml and "max_usd_per_project = 50.0" in toml and "IRB-42" in toml
    assert json.loads((p / ".aris" / "reviewer.json").read_text())["backend"] == "claude-review"
    for d in ("plans", "tasks", "artifacts", "runs", "reviews", "approvals", "kb/papers", "kb/notes", "memory", "checkpoints"):
        assert (p / ".research-agent" / d).is_dir()
    (p / ".research-agent" / "project.toml").write_text(toml + "\n# edited\n")
    setup.init_project(p, protected=[], sensitive=[], irb="", budget_session=1.0, budget_project=1.0)
    assert "# edited" in (p / ".research-agent" / "project.toml").read_text()
    gi = (p / ".gitignore").read_text()
    assert gi.count(".research-agent/runs/*/pip_freeze.txt") == 1


def test_cli_init_and_status(capsys, tmp_path, tmp_home, monkeypatch):
    p = tmp_path / "study"
    p.mkdir()
    monkeypatch.chdir(p)
    assert run(capsys, "init", "--protected", "data/raw")[0] == 0
    code, out = run(capsys, "status", "--json")
    data = json.loads(out)
    assert code == 0 and data["project"] == str(p.resolve()) and "budget" in data


def test_commands_need_project(capsys, tmp_path, tmp_home, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "budget", "show")
    assert code == 2


def test_kb_promote_without_approved_flag_exits_nonzero(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    meta = project / "m.json"
    meta.write_text(json.dumps({"title": "Gaze entropy", "authors": ["Kim"], "year": 2023}))
    assert run(capsys, "kb", "add", "--json-file", str(meta), "--scope", "project")[0] == 0
    code, out = run(capsys, "kb", "queue", "--json")
    ids = [q["id"] for q in json.loads(out)]
    assert len(ids) == 1
    assert run(capsys, "kb", "promote", "--ids", ids[0])[0] != 0
    assert run(capsys, "kb", "promote", "--ids", ids[0], "--approved")[0] == 0
    code, out = run(capsys, "kb", "search", "entropy", "--scope", "global", "--json")
    assert json.loads(out)[0]["scope"] == "global"


def test_loop_cli_roundtrip(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    assert run(capsys, "loop", "start", "--mode", "research", "survey MCI")[0] == 0
    _, out = run(capsys, "loop", "next", "--json")
    assert json.loads(out)["agent"] == "research"
    run(capsys, "loop", "next")
    run(capsys, "loop", "next")
    assert run(capsys, "loop", "verdict", "PASS")[0] == 0
    run(capsys, "loop", "checkpoint")
    _, out = run(capsys, "loop", "status", "--json")
    assert json.loads(out)["stop"] == {"stop": True, "reason": "reviewer_pass"}


def test_task_and_gate_cli(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    _, out = run(capsys, "task", "create", "Survey", "--agent", "research", "--type", "literature", "--json")
    tid = json.loads(out)["id"]
    assert run(capsys, "task", "move", tid, "dispatched")[0] == 0
    assert run(capsys, "task", "move", tid, "done")[0] != 0
    code, out = run(capsys, "gate", "check", tid, "--json")
    assert code == 1 and json.loads(out)["passed"] is False


def test_job_run_cli(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    code, out = run(capsys, "job", "run", "--seed", "1", "--", sys.executable, "-c", "print('hello')")
    assert code == 0 and "hello" in out and "run_id" in out


def test_approve_cli(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    ApprovalStore(project).request("publish", "git push", "x")
    _, out = run(capsys, "approve", "list", "--json")
    assert json.loads(out)[0]["rule"] == "publish"
    assert run(capsys, "approve", "grant", "publish", "git push")[0] == 0
    assert ApprovalStore(project).is_approved("publish", "git push")


def test_memory_cli(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    run(capsys, "memory", "decide", "Split", "--decision", "subject-level", "--rationale", "leakage")
    _, out = run(capsys, "memory", "show")
    assert "subject-level" in out


def test_run_dry_run_prints_options(capsys, project, monkeypatch):
    monkeypatch.chdir(project)
    code, out = run(capsys, "run", "--goal", "survey MCI gaze", "--loop", "research", "--budget-usd", "50", "--dry-run")
    opts = json.loads(out)
    assert code == 0 and opts["max_budget_usd"] == 10.0  # capped at max_usd_per_session
    assert opts["prompt"].startswith("/research-agent:ra survey MCI gaze --loop research")
    assert opts["setting_sources"] == ["user", "project", "local"]


def test_permission_callback_headless_denies_and_records(project):
    decide = sdk_runner.permission_callback(project, None)
    assert decide("Bash", {"command": "git push"}) [0] == "deny"
    assert ApprovalStore(project).pending()[0]["rule"] == "publish"
    assert "pending.md" in str(list((project / ".research-agent" / "approvals").iterdir()))
    assert decide("Bash", {"command": "echo x > data/raw/a"})[0] == "deny"
    assert decide("Bash", {"command": "ls"})[0] == "allow"


def test_doctor_flags_tutu(tmp_path, monkeypatch):
    home = make_claude_home(tmp_path)
    f = home / "plugins" / "installed_plugins.json"
    data = json.loads(f.read_text())
    data["plugins"]["superpowers@tutu"] = [{"scope": "user", "installPath": str(tmp_path)}]
    f.write_text(json.dumps(data))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    checks = {c.name: c for c in doctor.run()}
    assert not checks["no-tutu"].ok and checks["no-tutu"].level == "error"
    assert checks["plugin aris@aris"].ok and not checks["plugin research-agent@research-agent"].ok


def test_setup_machine_registers_reviewer(tmp_home, tmp_path, monkeypatch):
    home = make_claude_home(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    calls = []

    class R:
        def __init__(self, out=""):
            self.stdout, self.returncode = out, 0

    def runner(cmd, **kw):
        calls.append(cmd)
        return R("")

    actions = setup.setup_machine("claude", runner=runner)
    assert (tmp_home["ra"] / "knowledge" / "papers").is_dir() and (tmp_home["ra"] / "config.toml").is_file()
    assert any(c[:3] == ["claude", "mcp", "add"] and "claude-review" in c for c in calls)
    aris_repo = (tmp_path / "h" / ".aris" / "repo").read_text().strip()
    assert aris_repo.endswith("abc") and any("aris" in a for a in actions)


def test_marketplace_lists_only_self():
    mk = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    pl = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert [p["name"] for p in mk["plugins"]] == ["research-agent"] and mk["plugins"][0]["source"] == "./"
    assert "dependencies" not in pl and pl["name"] == "research-agent"


def test_commands_exist():
    names = sorted(p.stem for p in (ROOT / "commands").glob("*.md"))
    assert names == ["ra", "ra-approve", "ra-init", "ra-kb", "ra-loop", "ra-status"]


def test_agents_show(capsys):
    code, out = run(capsys, "agents", "show", "orchestrator")
    assert code == 0 and out.startswith("---\nname: orchestrator")


def test_bin_wrapper_runs(tmp_home):
    import subprocess
    r = subprocess.run(["bash", str(ROOT / "bin" / "ra"), "route", "survey gaze papers", "--json"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["agent"] == "research"


def test_setup_machine_repoints_stale_tutu_paths(tmp_home, tmp_path, monkeypatch):
    home = make_claude_home(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    old = tmp_path / "old-tutu-cache" / "aris"
    old.mkdir(parents=True)
    (tmp_path / "h" / ".aris").mkdir(parents=True)
    (tmp_path / "h" / ".aris" / "repo").write_text(str(old) + "\n")
    calls = []

    class R:
        def __init__(self, out=""):
            self.stdout, self.returncode = out, 0

    def runner(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["claude", "mcp", "list"]:
            return R(f"claude-review: /usr/bin/python3 {old}/mcp-servers/claude-review/server.py - ✔ Connected\n")
        return R()

    setup.setup_machine("claude", runner=runner)
    assert (tmp_path / "h" / ".aris" / "repo").read_text().strip().endswith("abc")
    assert ["claude", "mcp", "remove", "claude-review", "-s", "user"] in calls
    assert any(c[:4] == ["claude", "mcp", "add", "claude-review"] for c in calls)


def test_doctor_skills_mode_reports_optional_requirements(tmp_path, monkeypatch):
    home = make_claude_home(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    class R:
        stdout = "claude-review: python server.py - ✔ Connected\n"

    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: R())
    checks = {c.name: c for c in doctor.run(skills=True, live=True)}
    assert checks["skills aris"].level == "warn" and not checks["skills aris"].ok  # fixture has 5, not 87
    assert "aris:exa-search (env:EXA_API_KEY)" in checks["optional research"].detail
    assert checks["reviewer MCP"].ok and checks["reviewer MCP connected"].ok
