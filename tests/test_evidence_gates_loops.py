import pytest

from research_agent import config, evidence, gates, provenance
from research_agent.budget import Budget
from research_agent.loops import LOOPS, LoopController
from research_agent.tasks import TaskStore

DOC = """# Report

## Background
- Eye tracking is widely used (no label needed here).

## Findings
- Fixation duration is longer in MCI [SOURCED:kim2023_gaze].
- Our model reaches AUROC 0.81 [RUN:R1].
- Scanpath entropy may index executive dysfunction [HYPOTHESIS].
- This combination is under-studied [INFERRED].
- Unlabelled claim here.
- Ghost citation [SOURCED:ghost2020_x].
- Ghost run [RUN:R404].

## Conclusions
* Another unlabelled one.
"""


def test_lint_flags_unlabelled_and_unknown():
    issues = evidence.lint(DOC, {"kim2023_gaze"}, lambda r: r == "R1")
    kinds = sorted((i.kind, i.line) for i in issues)
    assert kinds == [("unknown-run", 13), ("unknown-source", 12), ("unlabelled", 11), ("unlabelled", 16)]


def test_lint_ignores_non_claim_sections():
    assert evidence.lint("## Background\n- anything\n", set(), lambda r: False) == []


def make_task(project):
    t = TaskStore(project).create("Survey", "research", "literature")
    adir = project / t["artifact_dir"]
    adir.mkdir(parents=True)
    return t["id"], adir


HANDOFF = "\n```handoff\ntask_id: {tid}\nstatus: done\nartifacts: [report.md]\nrun_ids: [{runs}]\nopen_issues: []\n```\n"


def test_gate_fails_without_handoff_then_passes_with_review(project):
    tid, adir = make_task(project)
    assert not gates.check(project, tid).passed  # no artifacts at all
    (adir / "report.md").write_text("## Findings\n- Gaze differs [INFERRED].\n")
    rep = gates.check(project, tid, stage="pre-review")
    assert not rep.passed and dict((n, ok) for n, ok, _ in rep.checks)["handoff"] is False
    (adir / "report.md").write_text("## Findings\n- Gaze differs [INFERRED].\n" + HANDOFF.format(tid=tid, runs=""))
    assert gates.check(project, tid, stage="pre-review").passed
    final = gates.check(project, tid)
    assert not final.passed and dict((n, ok) for n, ok, _ in final.checks)["review"] is False
    rev = project / ".research-agent" / "reviews"
    rev.mkdir(parents=True)
    (rev / f"{tid}.md").write_text("VERDICT: FAIL\nMUST_FIX:\n- leakage\n")
    assert not gates.check(project, tid).passed
    (rev / f"{tid}.md").write_text("VERDICT: PASS_WITH_FIXES\n")
    assert gates.check(project, tid).passed


def test_gate_checks_run_ids_and_evidence(project):
    tid, adir = make_task(project)
    (adir / "report.md").write_text("## Results\n- AUROC 0.8 [RUN:R404].\n" + HANDOFF.format(tid=tid, runs="R404"))
    rep = dict((n, ok) for n, ok, _ in gates.check(project, tid, stage="pre-review").checks)
    assert rep["evidence"] is False and rep["runs"] is False
    rid = provenance.capture(project, ["echo"], None, [], [])
    (adir / "report.md").write_text(f"## Results\n- AUROC 0.8 [RUN:{rid}].\n" + HANDOFF.format(tid=tid, runs=rid))
    assert gates.check(project, tid, stage="pre-review").passed


def test_gate_unknown_task(project):
    assert not gates.check(project, "T999").passed


def loop(project, **budget):
    cfg = config.load(project)
    cfg["budget"].update(budget)
    return LoopController(project, cfg)


def drain(lc):
    agents = []
    while (s := lc.next_step()) is not None:
        agents.append(s["agent"])
    return agents


def test_loop_full_order(project):
    lc = loop(project)
    lc.start("goal", "full")
    assert drain(lc) == LOOPS["full"] == ["research", "methodology", "coding", "experiment", "reviewer"]


def test_loop_stops_on_pass(project):
    lc = loop(project)
    lc.start("goal", "research")
    drain(lc)
    lc.record_verdict("PASS", [])
    assert lc.should_stop() == (True, "reviewer_pass")


def test_loop_stops_after_two_fails(project):
    lc = loop(project)
    lc.start("goal", "coding")
    for _ in range(2):
        assert lc.should_stop() == (False, "")
        drain(lc)
        lc.record_verdict("FAIL", ["fix leakage"])
        lc.checkpoint()
    assert lc.should_stop() == (True, "consecutive_fails")


def test_loop_max_iterations_and_must_fix_carried(project):
    lc = loop(project)
    lc.start("goal", "research")
    for i in range(3):
        assert not lc.should_stop()[0]
        steps = []
        while (s := lc.next_step()) is not None:
            steps.append(s)
        if i:
            assert steps[0]["must_fix"] == [f"fix {i - 1}"] and steps[0]["iteration"] == i + 1
        lc.record_verdict("PASS_WITH_FIXES", [f"fix {i}"])
        cp = lc.checkpoint()
        assert cp.is_file() and f"iter-{i + 1}" in cp.name
    assert lc.should_stop() == (True, "max_iterations")


def test_loop_budget_stop(project):
    lc = loop(project, max_usd_per_session=1.0)
    lc.start("goal", "full")
    assert lc.should_stop(session_usd=2.0, budget=Budget(project, lc.cfg)) == (True, "budget")


def test_loop_none_is_done(project):
    lc = loop(project)
    st = lc.start("goal", "none")
    assert st["done"] and lc.next_step() is None


def test_unknown_mode_raises(project):
    with pytest.raises(ValueError):
        loop(project).start("goal", "forever")


def test_loop_state_persists(project):
    lc = loop(project)
    lc.start("goal", "research")
    lc.next_step()
    assert loop(project).next_step()["agent"] == "methodology"
    assert loop(project).status()["mode"] == "research"
