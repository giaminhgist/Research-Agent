import json
import os
import subprocess
import sys
from pathlib import Path

from research_agent import config
from research_agent.budget import Budget
from research_agent.hooks import handle
from research_agent.memory import ProjectMemory
from test_budget import write_transcript

ROOT = Path(__file__).resolve().parents[1]


def pre(project, tool, tool_input, **extra):
    return {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(project), "tool_name": tool,
            "tool_input": tool_input, "transcript_path": extra.pop("transcript", ""), **extra}


def test_pretool_deny_json_shape(project):
    out = handle("PreToolUse", pre(project, "Bash", {"command": "echo x > data/raw/a.csv"}))
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse" and hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"].startswith("[research-agent:protected-write]")


def test_pretool_ask(project):
    out = handle("PreToolUse", pre(project, "Bash", {"command": "git push"}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_pretool_allow_returns_none(project):
    assert handle("PreToolUse", pre(project, "Bash", {"command": "ls"})) is None


def test_agent_dispatch_denied_over_session_cap(project, tmp_path):
    toml = project / ".research-agent" / "project.toml"
    toml.write_text(toml.read_text() + "\n[budget]\nmax_usd_per_session = 0.0001\n")
    t = write_transcript(tmp_path / "t.jsonl")
    out = handle("PreToolUse", pre(project, "Agent", {"subagent_type": "research-agent:research", "prompt": "x"}, transcript=str(t)))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "max_usd_per_session" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_agent_dispatch_warns_when_cost_unknown(project):
    out = handle("PreToolUse", pre(project, "Agent", {"prompt": "x"}, transcript="/nonexistent"))
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert "unknown" in out["hookSpecificOutput"]["additionalContext"]


def test_subagent_count_cap(project, tmp_path):
    toml = project / ".research-agent" / "project.toml"
    toml.write_text(toml.read_text() + "\n[budget]\nmax_subagents_per_session = 2\n")
    t = write_transcript(tmp_path / "t.jsonl")
    p = pre(project, "Agent", {"prompt": "x"}, transcript=str(t))
    assert handle("PreToolUse", p) is None
    assert handle("PreToolUse", p) is None
    out = handle("PreToolUse", p)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "max_subagents_per_session" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_reviewer_agent_type_respected(project):
    out = handle("PreToolUse", pre(project, "Write", {"file_path": str(project / "src/a.py")}, agent_type="research-agent:reviewer"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_posttool_provenance_nudge(project):
    p = {"session_id": "s1", "cwd": str(project), "tool_name": "Bash", "tool_input": {"command": "python train.py --epochs 3"}}
    out = handle("PostToolUse", p)
    assert "ra job run" in out["hookSpecificOutput"]["additionalContext"]
    p["tool_input"]["command"] = "ra job run --seed 0 -- python train.py"
    assert handle("PostToolUse", p) is None


def test_session_start_context_and_path(project, tmp_path):
    ProjectMemory(project).decide("Split", "subject-level 5-fold", "leakage")
    env_file = tmp_path / "env.sh"
    out = handle("SessionStart", {"session_id": "s1", "cwd": str(project)}, env={"CLAUDE_ENV_FILE": str(env_file)})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "subject-level 5-fold" in ctx and "Budget" in ctx
    assert "PATH=" in env_file.read_text()


def test_subagent_stop_queues_knowledge(project):
    from research_agent import kb
    kb.add_paper({"title": "Gaze entropy in MCI", "authors": ["Kim"], "year": 2023}, "x", "project", project)
    out = handle("SubagentStop", {"session_id": "s1", "cwd": str(project), "agent_type": "research-agent:research"})
    assert "1 knowledge item" in out["systemMessage"]
    assert handle("SubagentStop", {"session_id": "s1", "cwd": str(project), "agent_type": "research-agent:coding"}) is None


def test_stop_records_session(project, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl")
    handle("Stop", {"session_id": "s9", "cwd": str(project), "transcript_path": str(t)})
    assert Budget(project).project_total() > 0.1


def test_outside_project_noop_creates_nothing(tmp_path, tmp_home):
    plain = tmp_path / "plain"
    plain.mkdir()
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    for ev, payload in [
        ("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "git push"}}),
        ("PreToolUse", {"tool_name": "Agent", "tool_input": {"prompt": "x"}}),
        ("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "python train.py"}}),
        ("SessionStart", {}), ("SubagentStop", {"agent_type": "research"}), ("Stop", {}), ("SessionEnd", {}),
    ]:
        assert handle(ev, {"session_id": "s", "cwd": str(plain), **payload}, env={}) is None
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_outside_project_universal_deny(tmp_path, tmp_home):
    out = handle("PreToolUse", {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_dispatch_script_end_to_end(project, tmp_home):
    payload = json.dumps(pre(project, "Bash", {"command": "echo x > data/raw/a.csv"}))
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "dispatch.py"), "PreToolUse"], input=payload, text=True,
                       capture_output=True, env=env, cwd=project)
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_dispatch_script_survives_bad_input(project, tmp_home):
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "dispatch.py"), "PreToolUse"], input="{not json", text=True,
                       capture_output=True, cwd=project)
    assert r.returncode == 0 and r.stdout == ""


def test_hooks_json_events():
    data = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(data) == {"PreToolUse", "PostToolUse", "SessionStart", "SubagentStop", "Stop", "SessionEnd"}
    assert "Agent" in data["PreToolUse"][0]["matcher"]
