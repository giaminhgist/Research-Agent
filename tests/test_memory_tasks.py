import pytest

from research_agent.memory import ProjectMemory
from research_agent.tasks import TaskStore
from research_agent import trace


def test_task_lifecycle(project):
    ts = TaskStore(project)
    t = ts.create("Survey MCI eye tracking", "research", "literature")
    assert t["id"] == "T001" and t["state"] == "planned"
    assert t["artifact_dir"] == ".research-agent/artifacts/T001"
    assert ts.create("x", "coding", "implement")["id"] == "T002"
    for s in ("dispatched", "artifact_ready", "in_review", "passed", "done"):
        ts.transition("T001", s)
    assert ts.get("T001")["state"] == "done"
    assert [h["state"] for h in ts.get("T001")["history"]][-1] == "done"
    assert [t["id"] for t in ts.list(state="planned")] == ["T002"]


def test_task_illegal_transition(project):
    ts = TaskStore(project)
    ts.create("x", "coding", "implement")
    with pytest.raises(ValueError):
        ts.transition("T001", "passed")
    with pytest.raises(KeyError):
        ts.transition("T999", "dispatched")


def test_memory_summary_truncates(project):
    m = ProjectMemory(project)
    for i in range(8):
        m.decide(f"Decision {i}", "use subject-level CV", "avoid leakage")
        m.progress(f"step {i} done")
    m.update_state(plan="P1", loop_iteration=2)
    s = m.summary(max_chars=400)
    assert len(s) <= 400
    full = m.summary()
    assert "Decision 7" in full and "Decision 2" not in full and "plan" in full
    assert m.state()["loop_iteration"] == 2
    assert "## Decision 0" in (project / ".research-agent" / "memory" / "decisions.md").read_text()


def test_trace_append_read(project):
    trace.append(project, "kb.promote", ids=["a"])
    assert trace.read(project)[-1]["event"] == "kb.promote"
