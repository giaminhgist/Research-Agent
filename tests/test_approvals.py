from research_agent.approvals import ApprovalStore


def test_grant_expiry(project):
    s = ApprovalStore(project)
    s.grant("phi-read", "data/phi", ttl_hours=1)
    import time
    now = time.time()
    assert s.is_approved("phi-read", "data/phi", now=now)
    assert not s.is_approved("phi-read", "data/phi", now=now + 7200)
    assert not s.is_approved("phi-read", "other", now=now)


def test_wildcard_grant(project):
    s = ApprovalStore(project)
    s.grant("publish")
    assert s.is_approved("publish", "git push origin main")


def test_headless_request_writes_pending_md(project):
    s = ApprovalStore(project)
    r = s.request("publish", "git push", "pushes to remote", headless=True)
    assert r["id"] and s.pending()[0]["rule"] == "publish"
    md = (project / ".research-agent" / "approvals" / "pending.md").read_text()
    assert "git push" in md and "ra approve grant publish" in md


def test_grant_clears_pending(project):
    s = ApprovalStore(project)
    s.request("publish", "git push", "x")
    s.grant("publish", "git push")
    assert s.pending() == []
