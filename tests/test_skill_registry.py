import json
from pathlib import Path

import pytest

from fixtures_claude import make_claude_home
from research_agent import frontmatter
from research_agent.skill_registry import SkillRegistry


@pytest.fixture
def reg(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills" / "proj-skill").mkdir(parents=True)
    (proj / ".claude" / "skills" / "proj-skill" / "SKILL.md").write_text("---\nname: proj-skill\ndescription: p\n---\n")
    return SkillRegistry.discover(make_claude_home(tmp_path), project=proj)


def test_discovers_plugin_user_and_builtin(reg):
    assert reg.get("aris:research-lit").invoke_as == "aris:research-lit"
    assert reg.get("aris:research-lit").installed
    ds = reg.get("supervisor-skills:deep-research")
    assert ds.invoke_as == "deep-research" and ds.installed and ds.source == "supervisor-skills"
    assert reg.get("builtin:code-review").installed
    assert reg.get("humanizer:humanizer").installed
    assert reg.get("superpowers:brainstorming").description == "Use before creative work"


def test_lookup_by_invoke_name_and_bare_name(reg):
    assert reg.get("deep-research").id == "supervisor-skills:deep-research"
    assert reg.get("code-review").id == "builtin:code-review"
    assert reg.get("user:my-own-skill").installed
    assert reg.get("project:proj-skill").installed


def test_codex_mirrors_and_dirs_without_skill_md_ignored(reg):
    assert reg.counts_by_source()["aris"] == 5


def test_aris_dependencies_from_tsv(reg):
    assert "aris:paper-plan" in reg.dependency_closure(["aris:paper-writing"])
    order = reg.dependency_closure(["aris:paper-writing"])
    assert order.index("aris:paper-plan") < order.index("aris:paper-writing")


def test_dependency_cycle_safe(reg):
    reg.get("aris:paper-plan").depends_on.append("aris:paper-writing")
    assert set(reg.dependency_closure(["aris:paper-writing"])) == {"aris:paper-writing", "aris:paper-plan", "aris:figure-spec"}


def test_availability_env(reg):
    assert reg.available("aris:exa-search", env={}) == (False, ["env:EXA_API_KEY"])
    assert reg.available("aris:exa-search", env={"EXA_API_KEY": "x"}) == (True, [])


def test_not_installed(reg):
    assert reg.available("aris:paper-compile", env={})[0] is False
    assert "not installed" in reg.available("aris:paper-compile", env={})[1]


def test_unknown_id_not_available(reg):
    assert reg.available("aris:does-not-exist", env={}) == (False, ["unknown skill"])


def test_frontmatter_block_scalar():
    meta, body = frontmatter.parse("---\nname: x\ndescription: >\n  a\n  b\ntags:\n  - one\n  - two\nq: \"hi: there\"\n---\nBODY\n")
    assert meta == {"name": "x", "description": "a b", "tags": ["one", "two"], "q": "hi: there"}
    assert body == "BODY\n"


def test_frontmatter_absent():
    assert frontmatter.parse("plain") == ({}, "plain")


REAL = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


@pytest.mark.skipif(not REAL.is_file(), reason="no real Claude install")
def test_real_machine_counts():
    counts = SkillRegistry.discover(Path.home() / ".claude").counts_by_source()
    assert counts.get("aris") == 87
    assert counts.get("superpowers") == 15
    assert counts.get("humanizer") == 1
    assert counts.get("supervisor-skills") == 12


@pytest.mark.skipif(not REAL.is_file(), reason="no real Claude install")
def test_every_installed_upstream_skill_is_catalogued_or_unmapped():
    r = SkillRegistry.discover(Path.home() / ".claude")
    import tomllib
    from research_agent.skill_registry import default_catalog_path
    cat = tomllib.load(default_catalog_path().open("rb"))
    known = set(cat["skills"]) | set(cat["unmapped"]["ids"])
    left = [s.id for s in r.all() if s.installed and s.source in ("aris", "superpowers", "supervisor-skills", "humanizer") and s.id not in known]
    assert left == []
