import json

import pytest

from research_agent import config
from research_agent.budget import Budget, session_cost_from_transcript


def write_transcript(path):
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"id": "A", "model": "claude-opus-5-5", "usage": {"input_tokens": 1000, "output_tokens": 2000}}},
        "not json at all",
        {"type": "assistant", "message": {"id": "A", "model": "claude-opus-5-5", "usage": {"input_tokens": 1000, "output_tokens": 3000}}},
        {"type": "assistant", "message": {"id": "B", "model": "claude-sonnet-5-5", "usage": {
            "input_tokens": 10000, "output_tokens": 1000, "cache_creation_input_tokens": 4000, "cache_read_input_tokens": 100000}}},
    ]
    path.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines) + "\n")
    return path


def test_transcript_cost_dedupes(tmp_path, project):
    pricing = config.load(project)["pricing"]
    cost = session_cost_from_transcript(write_transcript(tmp_path / "t.jsonl"), pricing)
    # A (last line wins): 1000*4 + 3000*20 = 64000 ; B: 10000*2 + 1000*10 + 4000*2.5 + 100000*0.2 = 60000 ; /1e6
    assert cost == pytest.approx(0.124)


def test_missing_transcript_none(tmp_path, project):
    assert session_cost_from_transcript(tmp_path / "nope.jsonl", config.load(project)["pricing"]) is None


def budget(project, **over):
    cfg = config.load(project)
    cfg["budget"].update(over)
    return Budget(project, cfg)


def test_session_cap_denies(project):
    b = budget(project, max_usd_per_session=1.0)
    assert b.check_dispatch("s1", 1.0)[0] == "deny"
    assert b.check_dispatch("s1", 0.1)[0] == "allow"


def test_project_cap_denies_across_sessions(project):
    b = budget(project, max_usd_per_project=100.0, max_usd_per_session=1000.0)
    b.record_session("s1", 60.0)
    b.record_session("s2", 45.0)
    action, msg = b.check_dispatch("s3", 0.0)
    assert action == "deny" and "project" in msg


def test_latest_session_record_wins(project):
    b = budget(project)
    b.record_session("s1", 5.0)
    b.record_session("s1", 7.0)
    assert b.project_total() == 7.0
    assert b.project_total(override=("s1", 2.0)) == 2.0


def test_warn_at_80pct(project):
    b = budget(project, max_usd_per_session=10.0)
    assert b.check_dispatch("s1", 8.5)[0] == "warn"


def test_unknown_cost_warns_but_project_cap_enforced(project):
    b = budget(project, max_usd_per_project=10.0)
    assert b.check_dispatch("s1", None)[0] == "warn"
    b.record_session("old", 11.0)
    assert b.check_dispatch("s1", None)[0] == "deny"


def test_gpu_job_cap_and_timeout(project):
    b = budget(project)  # 5 USD cap, 1.5 USD/h
    assert b.check_gpu_job(2) == (True, 3.0, 7200)
    ok, est, _ = b.check_gpu_job(4)
    assert not ok and est == 6.0
    assert b.check_gpu_job(0) == (True, 0.0, 0)


def test_gpu_jobs_count_toward_project(project):
    b = budget(project)
    assert b.record_gpu_job("R1", 2.0) == 3.0
    assert b.project_total() == 3.0
    assert b.summary()["gpu_usd"] == 3.0
