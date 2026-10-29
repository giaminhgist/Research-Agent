import tomllib
from pathlib import Path

import pytest

from fixtures_claude import make_claude_home
from research_agent import agent_registry, frontmatter
from research_agent.agent_factory import build_all
from research_agent.agent_registry import AGENT_NAMES, AgentSpec, RegistryError, load_agents, validate
from research_agent.routing_policy import route
from research_agent.skill_registry import SkillRegistry, default_catalog_path
from research_agent.skill_resolver import resolve

ROOT = Path(__file__).resolve().parents[1]
CATALOG = tomllib.load(default_catalog_path().open("rb"))
CAT_IDS = set(CATALOG["skills"])


def test_registry_valid():
    agents = load_agents()
    assert tuple(sorted(agents)) == tuple(sorted(AGENT_NAMES))
    for a in agents.values():
        assert set(a.core_skills) <= CAT_IDS and set(a.borrow_skills) <= CAT_IDS


def test_models_follow_spec():
    agents = load_agents()
    assert {n: a.model for n, a in agents.items()} == {
        "orchestrator": "opus", "research": "sonnet", "methodology": "opus", "coding": "sonnet",
        "experiment": "sonnet", "writing": "opus", "reviewer": "opus",
    }


def test_validate_rejects_unknown_skill_and_tool():
    a = load_agents()["research"]
    bad = dict(load_agents())
    bad["research"] = AgentSpec(**{**a.__dict__, "core_skills": a.core_skills + ["aris:nope"], "tools": a.tools + ["Teleport"]})
    errs = validate(bad, CAT_IDS)
    assert any("aris:nope" in e for e in errs) and any("Teleport" in e for e in errs)


def test_load_raises_registry_error(tmp_path):
    p = tmp_path / "agents.toml"
    p.write_text('[agents.research]\nmodel = "gpt"\n')
    with pytest.raises(RegistryError):
        load_agents(p)


def test_core_counts():
    for a in load_agents().values():
        assert 8 <= len(a.core_skills) <= 12, a.name


def test_unmapped_documented():
    agents = load_agents()
    mapped = {s for a in agents.values() for s in a.core_skills + a.borrow_skills}
    doc = (ROOT / "docs" / "SKILLS.md").read_text()
    for sid in CATALOG["unmapped"]["ids"]:
        assert sid not in mapped
        assert sid in doc, sid


@pytest.mark.parametrize("task,agent", [
    ("survey eye-tracking biomarkers for Alzheimer's", "research"),
    ("propose hypotheses and an ablation plan", "methodology"),
    ("implement a GRU baseline in PyTorch", "coding"),
    ("run 5-fold CV and compute bootstrap CIs", "experiment"),
    ("draft the Methods section in LaTeX", "writing"),
    ("review the training code for data leakage", "reviewer"),
])
def test_route_examples(task, agent):
    assert route(task).agent == agent


def test_route_fallback():
    r = route("hello")
    assert r.agent == "orchestrator" and r.confidence == 0 and r.task_type == "plan"


def test_review_never_author():
    r = route("check this code", task_type="review", author_agent="coding")
    assert r.agent == "reviewer" and "fresh context" in r.rationale


@pytest.fixture
def reg(tmp_path):
    return SkillRegistry.discover(make_claude_home(tmp_path))


def test_resolver_borrows_and_flags_missing(reg):
    agents = load_agents()
    res = resolve("search exa for scanpath papers", agents["research"], reg, env={})
    assert ("aris:exa-search", "env:EXA_API_KEY") in res.missing
    res = resolve("search exa for scanpath papers", agents["research"], reg, env={"EXA_API_KEY": "k"})
    assert "aris:exa-search" in [b for b, _ in res.borrowed]
    res = resolve("make conference slides", agents["writing"], reg, env={})
    selected = [b for b, _ in res.borrowed] + [m for m, _ in res.missing]
    assert "aris:paper-slides" in selected


def test_resolver_core_preload_and_missing_core(reg):
    res = resolve("anything", load_agents()["research"], reg, env={})
    assert "aris:research-lit" in res.preload and "deep-research" in res.preload
    assert any(sid == "aris:arxiv" and why == "not installed" for sid, why in res.missing)


def test_resolver_dependency_closure(reg):
    res = resolve("full paper pipeline to pdf", load_agents()["writing"], reg, task_type="write", env={})
    assert "aris:figure-spec" in res.dependencies
    assert "aris:paper-plan" not in res.dependencies  # already a core skill


def test_agents_in_sync():
    assert build_all(ROOT / "agents", check=True) == []


def test_agent_frontmatter_shape():
    files = sorted((ROOT / "agents").glob("*.md"))
    assert [f.stem for f in files] == sorted(AGENT_NAMES)
    for f in files:
        meta, body = frontmatter.parse(f.read_text())
        assert {"name", "description", "tools", "skills", "model"} <= set(meta)
        assert isinstance(meta["skills"], list) and meta["skills"]
        assert body.lstrip().startswith("You are") and "Responsibilities:" in body
