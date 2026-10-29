import pytest

from research_agent import kb, paths


def meta(title="Scanpath transformers for MCI", authors=("Nguyễn Văn A", "B. Smith"), year=2024, **kw):
    return {"title": title, "authors": list(authors), "year": year, "venue": "MICCAI", "arxiv": "2401.00001", "tags": ["eye-tracking", "mci"], **kw}


def test_slug_ascii():
    assert kb.paper_slug(meta()) == "nguyen2024_scanpath"
    assert kb.paper_slug(meta(title="A study of the gaze", authors=["Lee, J."], year=2020)) == "lee2020_study"


def test_add_and_search_project_and_global(project, tmp_home):
    p = kb.add_paper(meta(), "Transformers over fixation sequences detect MCI.", "project", project)
    assert p.is_file() and paths.is_within(p, project)
    g = kb.add_paper(meta(title="Pupillometry in Alzheimer disease", authors=["Chen"], year=2021), "Pupil dilation.", "global", None)
    assert paths.is_within(g, tmp_home["ra"])
    hits = kb.search("fixation", project, scope="all")
    assert hits and hits[0].scope == "project" and "nguyen2024_scanpath" in str(hits[0].path)
    assert [h.scope for h in kb.search("pupil", project)] == ["global"]
    assert kb.search("pupil", project, scope="project") == []
    assert "nguyen2024_scanpath" in (project / ".research-agent" / "kb" / "library.bib").read_text()
    assert {"nguyen2024_scanpath", "chen2021_pupillometry"} <= kb.bib_keys(project)


def test_search_reindexes_after_change(project):
    p = kb.add_paper(meta(), "alpha", "project", project)
    assert kb.search("alpha", project)
    p.write_text(p.read_text().replace("alpha", "omega"))
    import os, time
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert kb.search("omega", project) and not kb.search("alpha", project)


def test_scope_isolation(tmp_path, tmp_home):
    a, b = tmp_path / "A", tmp_path / "B"
    for d in (a, b):
        (d / ".research-agent").mkdir(parents=True)
    kb.add_paper(meta(), "secret saccade finding", "project", a)
    assert kb.search("saccade", b, scope="all") == []
    assert kb.search("saccade", a, scope="all")


def test_queue_and_promote_requires_approval(project, tmp_home):
    kb.add_paper(meta(), "body", "project", project)
    q = kb.queue_candidates(project, origin_agent="research")
    assert len(q) == 1 and q[0]["status"] == "queued" and q[0]["kind"] == "paper"
    assert kb.queue_candidates(project) == []  # already queued
    with pytest.raises(PermissionError):
        kb.promote(project, [q[0]["id"]], approved=False)
    out = kb.promote(project, [q[0]["id"]], approved=True)
    text = out[0].read_text()
    assert paths.is_within(out[0], tmp_home["ra"]) and "promoted_from: proj" in text
    assert kb.list_queue(project) == []
    assert kb.list_queue(project, status="promoted")[0]["id"] == q[0]["id"]


def test_queue_skips_already_global(project, tmp_home):
    kb.add_paper(meta(), "x", "global", None)
    kb.add_paper(meta(), "x", "project", project)
    assert kb.queue_candidates(project) == []


def test_queue_notes_and_since(project):
    notes = project / ".research-agent" / "kb" / "notes"
    notes.mkdir(parents=True)
    (notes / "gap.md").write_text("---\ntitle: Gap in MCI scanpath work\n---\nNo external validation.\n")
    assert kb.queue_candidates(project)[0]["kind"] == "note"
    import time
    assert kb.queue_candidates(project, since=time.time() + 100) == []


def test_dismiss(project):
    kb.add_paper(meta(), "x", "project", project)
    q = kb.queue_candidates(project)
    assert kb.dismiss(project, [q[0]["id"]]) == 1
    assert kb.list_queue(project) == []
