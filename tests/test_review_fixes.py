"""Regression tests for the final whole-branch review findings (C1, I1-I7)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from research_agent import config, hooks, provenance
from research_agent.approvals import ApprovalStore
from research_agent.budget import Budget
from research_agent.guard import evaluate
from research_agent.loops import LoopController

ROOT = Path(__file__).resolve().parents[1]


def g(project, tool, inp, cwd=None):
    return evaluate(tool, inp, cwd or project, config.load(project), project, approvals=ApprovalStore(project))


def b(project, cmd, cwd=None):
    return g(project, "Bash", {"command": cmd}, cwd)


# ---- C1: no self-approval, no self-raised caps, no self-certified promotion ------------------------------------------
@pytest.mark.parametrize("cmd", [
    "ra approve grant phi-read '*'",
    "ra approve grant publish",
    "python -m research_agent approve grant publish",
    "echo x > .research-agent/project.toml",
    "sed -i 's/10.0/999.0/' .research-agent/project.toml",
    "echo '{}' >> .research-agent/approvals/granted.jsonl",
    "rm .research-agent/budget.jsonl",
    "ra kb promote --ids x --approved",
    "python -m research_agent kb promote --ids x --approved",
])
def test_self_governance_asks(project, cmd):
    d = b(project, cmd)
    assert d.action == "ask" and d.rule in ("self-govern", "kb-promote"), (cmd, d)


@pytest.mark.parametrize("tool,rel", [("Write", ".research-agent/project.toml"), ("Edit", ".research-agent/approvals/granted.jsonl"),
                                      ("Write", ".research-agent/budget.jsonl")])
def test_self_governance_tools_ask(project, tool, rel):
    assert g(project, tool, {"file_path": str(project / rel)}).rule == "self-govern"


def test_user_config_write_asks(project, tmp_home):
    assert g(project, "Write", {"file_path": str(tmp_home["ra"] / "config.toml")}).rule == "self-govern"


def test_reading_and_ra_cli_state_writes_still_allowed(project):
    assert b(project, "cat .research-agent/project.toml").action == "allow"
    assert b(project, "ra loop next").action == "allow"
    assert b(project, "ra approve list").action == "allow"


def test_budget_deny_message_addresses_user(project, tmp_path):
    from test_budget import write_transcript
    toml = project / ".research-agent" / "project.toml"
    toml.write_text(toml.read_text() + "\n[budget]\nmax_usd_per_session = 0.0001\n")
    out = hooks.handle("PreToolUse", {"session_id": "s", "cwd": str(project), "tool_name": "Agent", "tool_input": {},
                                      "transcript_path": str(write_transcript(tmp_path / "t.jsonl"))})
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Do not edit" in reason and "user" in reason


# ---- I1: cd chains ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cmd", ["cd .. && rm -rf proj", "cd / && rm -rf tmp", "cd .. ; rm -rf ./proj"])
def test_rm_after_cd_outside_denied(project, cmd):
    assert b(project, cmd).action == "deny"


def test_cd_into_phi_then_cat_asks(project):
    (project / "data/phi/sub").mkdir()
    assert b(project, "cd data/phi/sub && cat p.csv").rule == "phi-read"


def test_cd_subdir_rm_inside_allowed(project):
    (project / "build").mkdir()
    assert b(project, "cd build && rm -rf tmp").action == "allow"


# ---- I2: more write paths into protected data -----------------------------------------------------------------------
@pytest.mark.parametrize("cmd", [
    "git checkout -- data/raw", "git restore data/raw/a.csv", "git checkout -- .", "git clean -fdx", "git stash -u",
    "git reset --hard", "find data/raw -name '*.csv' -delete", "find data/raw -type f -exec rm {} \;",
    "find data/raw -name '*.csv' | xargs rm", "bash -c 'echo x > data/raw/a.csv'", "sh -c \"rm data/raw/a.csv\"",
    "eval 'rm data/raw/a.csv'", "unzip data.zip -d data/raw", "tar xzf d.tgz -C data/raw", "wget -O data/raw/x.csv http://x",
    "curl -o data/raw/x.csv http://x", "curl --output data/raw/x.csv http://x", "perl -i -pe 's/a/b/' data/raw/a.csv",
    "chmod -R a+w data/raw", "chown -R me data/raw", "rm -rf data", "mv data data_old",
])
def test_more_protected_writes_denied(project, cmd):
    d = b(project, cmd)
    assert d.action == "deny" and d.rule == "protected-write", (cmd, d)


@pytest.mark.parametrize("cmd", ["perl -pe 's/a/b/' data/raw/a.csv > out.csv", "ruby -ne 'puts 1' data/raw/a.csv"])
def test_inline_perl_ruby_flags_ask(project, cmd):
    assert b(project, cmd).rule == "inline-protected"


@pytest.mark.parametrize("cmd", ["git status", "git checkout -b feature", "find data/raw -name '*.csv'", "curl -o out.csv http://x",
                                 "python train.py --data data/raw/a.csv", "tar czf backup.tgz data/raw", "git stash"])
def test_benign_commands_allowed(project, cmd):
    assert b(project, cmd).action == "allow", cmd


# ---- I7: sensitive data read through a parent directory --------------------------------------------------------------
@pytest.mark.parametrize("tool,inp", [("Grep", {"pattern": "x", "path": "data"}), ("Glob", {"pattern": "data/**/*.csv"}),
                                      ("Grep", {"pattern": "x"})])
def test_sensitive_parent_dir_tools_ask(project, tool, inp):
    assert g(project, tool, inp).rule == "phi-read"


@pytest.mark.parametrize("cmd", ["grep -r x data/", "rg x data", "find data -name '*.csv'", "tar czf all.tgz data", "cp -r data /tmp/x"])
def test_sensitive_parent_dir_bash_asks(project, cmd):
    assert b(project, cmd).rule == "phi-read", cmd


def test_plain_ls_of_parent_allowed(project):
    assert b(project, "ls data").action == "allow"


# ---- I3: loop budget stop reachable from the CLI ---------------------------------------------------------------------
def test_loop_status_reports_budget(project):
    cfg = config.load(project)
    cfg["budget"]["max_usd_per_project"] = 1.0
    Budget(project, cfg).record_session("s", 2.0)
    lc = LoopController(project, cfg)
    lc.start("goal", "research")
    assert lc.status()["stop"] == {"stop": True, "reason": "budget"}


# ---- I4: manifests record the job's interpreter ---------------------------------------------------------------------
def test_manifest_records_job_interpreter(project):
    rid = provenance.capture(project, ["python3", "-c", "print(1)"], None, [], [])
    m = json.loads((project / ".research-agent/runs" / rid / "manifest.json").read_text())
    import shutil
    assert m["env"]["executable"] == shutil.which("python3")
    assert m["env"]["ra_executable"] == sys.executable
    assert m["env"]["python"]


def test_manifest_non_python_command_uses_path_python(project):
    rid = provenance.capture(project, ["bash", "run.sh"], None, [], [])
    m = json.loads((project / ".research-agent/runs" / rid / "manifest.json").read_text())
    assert m["env"]["executable"]


# ---- I5: GPU job timeout = cap / rate --------------------------------------------------------------------------------
def test_gpu_timeout_is_cap_over_rate(project):
    assert Budget(project).check_gpu_job(1) == (True, 1.5, 12000)  # 5 USD / 1.5 USD/h = 3.33 h


# ---- I6: Windows paths and spaces ------------------------------------------------------------------------------------
def test_bash_path_conversion():
    assert hooks.to_bash_path("C:\\Users\\a b\\x") == "/c/Users/a b/x"
    assert hooks.to_bash_path("/home/a/x") == "/home/a/x"


def test_run_sh_uses_venv_python_when_home_has_space(tmp_path):
    home = tmp_path / "my home"
    venv_bin = home / ".research-agent" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    marker = tmp_path / "used-venv"
    fake = venv_bin / "python"
    fake.write_text(f"#!/bin/sh\ntouch '{marker}'\nexec '{sys.executable}' \"$@\"\n")
    fake.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    env.pop("RA_PYTHON", None)
    r = subprocess.run(["bash", str(ROOT / "hooks" / "run.sh"), "PreToolUse"], input="{}", text=True, capture_output=True, env=env, cwd=tmp_path)
    assert r.returncode == 0 and marker.exists()
