import pytest

from research_agent import config
from research_agent.approvals import ApprovalStore
from research_agent.guard import evaluate


@pytest.fixture
def g(project):
    cfg = config.load(project)

    def run(tool, tool_input, cwd=None, agent=None, cfg_over=None, proj=project):
        c = dict(cfg)
        if cfg_over:
            c = {**c, **cfg_over}
        return evaluate(tool, tool_input, cwd or project, c, proj, agent=agent, approvals=ApprovalStore(project) if proj else None)
    return run


def bash(cmd):
    return {"command": cmd}


def test_write_tool_protected_denied(g, project):
    d = g("Write", {"file_path": str(project / "data/raw/a.csv"), "content": "x"})
    assert d.action == "deny" and d.rule == "protected-write"


def test_edit_outside_protected_allowed(g, project):
    assert g("Edit", {"file_path": str(project / "src/x.py")}).action == "allow"


def test_bash_redirect_protected_denied(g):
    assert g("Bash", bash("echo x > data/raw/a.csv")).action == "deny"


def test_cd_then_rm_denied(g):
    assert g("Bash", bash("cd data/raw && rm a.csv")).action == "deny"


def test_tee_denied(g):
    assert g("Bash", bash("python make.py | tee data/raw/out.txt")).action == "deny"


def test_cp_mv_destination_and_sed_i_denied(g):
    assert g("Bash", bash("cp /tmp/x.csv data/raw/")).action == "deny"
    assert g("Bash", bash("mv data/raw/a.csv data/raw/b.csv")).action == "deny"
    assert g("Bash", bash("sed -i 's/a/b/' data/raw/a.csv")).action == "deny"


def test_copy_from_protected_allowed(g):
    assert g("Bash", bash("cp data/raw/a.csv data/derived/a.csv")).action == "allow"


def test_windows_and_dotdot_paths_denied(g, project):
    assert g("Write", {"file_path": "data\\raw\\a.csv"}).action == "deny"
    assert g("Write", {"file_path": "./data/raw/../raw/a.csv"}).action == "deny"
    assert g("Bash", bash("echo x > ./data/raw/../raw/b.csv")).action == "deny"


def test_inline_python_mentioning_protected_asks(g):
    d = g("Bash", bash("python -c \"open('data/raw/a.csv','w').write('x')\""))
    assert d.action == "ask" and d.rule == "inline-protected"


def test_read_protected_allowed(g, project):
    assert g("Read", {"file_path": str(project / "data/raw/a.csv")}).action == "allow"
    assert g("Bash", bash("head data/raw/a.csv")).action == "allow"


def test_phi_read_asks_until_granted(g, project):
    d = g("Read", {"file_path": str(project / "data/phi/p1.csv")})
    assert d.action == "ask" and d.rule == "phi-read"
    ApprovalStore(project).grant("phi-read")
    assert g("Read", {"file_path": str(project / "data/phi/p1.csv")}).action == "allow"


def test_phi_grep_and_bash_ask(g):
    assert g("Grep", {"pattern": "x", "path": "data/phi"}).action == "ask"
    assert g("Bash", bash("cat data/phi/p1.csv")).action == "ask"


@pytest.mark.parametrize("cmd", ["git push origin main", "git -C repo push", "gh pr create --fill", "gh release create v1",
                                 "twine upload dist/*", "npm publish"])
def test_publish_asks(g, cmd):
    d = g("Bash", bash(cmd))
    assert d.action == "ask" and d.rule == "publish"


def test_git_commit_allowed(g):
    assert g("Bash", bash("git commit -m 'x'")).action == "allow"


def test_curl_post_asks_get_allowed(g):
    assert g("Bash", bash("curl -X POST https://x.io -d @data.json")).rule == "network-send"
    assert g("Bash", bash("curl -s https://api.semanticscholar.org/graph/v1/paper/search?query=x")).action == "allow"
    assert g("Bash", bash("scp results.csv host:/tmp")).action == "ask"


@pytest.mark.parametrize("cmd", ["vastai create instance 1", "modal run train.py", "sbatch job.sh", "qsub job.pbs"])
def test_cloud_gpu_asks(g, cmd):
    assert g("Bash", bash(cmd)).rule == "cloud-gpu"


def test_gpu_over_cap_asks(g):
    d = g("Bash", bash("ra job run --gpu-hours 4 -- python train.py"))
    assert d.action == "ask" and d.rule == "gpu-over-cap"
    assert g("Bash", bash("ra job run --gpu-hours 2 -- python train.py")).action == "allow"


def test_kb_promote_asks_without_approved(g):
    assert g("Bash", bash("ra kb promote --ids a1")).rule == "kb-promote"


def test_rm_rf_outside_denied(g, project):
    assert g("Bash", bash("rm -rf /")).action == "deny"
    assert g("Bash", bash("rm -rf ~")).action == "deny"
    assert g("Bash", bash(f"rm -rf {project.parent}")).action == "deny"
    assert g("Bash", bash("rm -rf build")).action == "allow"


def test_cross_project_read_denied(g, project, tmp_path):
    other = tmp_path / "other" / ".research-agent" / "memory" / "decisions.md"
    d = g("Read", {"file_path": str(other)})
    assert d.action == "deny" and d.rule == "cross-project"
    assert g("Bash", bash(f"cat {other}")).action == "deny"
    assert g("Read", {"file_path": str(project / ".research-agent" / "memory" / "x.md")}).action == "allow"


def test_reviewer_write_scope(g, project):
    assert g("Write", {"file_path": str(project / "src/x.py")}, agent="reviewer").action == "deny"
    assert g("Write", {"file_path": str(project / ".research-agent/reviews/T001.md")}, agent="research-agent:reviewer").action == "allow"


def test_supervised_pip_install_asks_semi_allows(g):
    assert g("Bash", bash("pip install numpy")).action == "allow"
    d = g("Bash", bash("pip install numpy"), cfg_over={"autonomy": {"level": "supervised"}})
    assert d.action == "ask"


def test_autonomous_never_relaxes_deny_or_publish(g):
    over = {"autonomy": {"level": "autonomous"}}
    assert g("Bash", bash("echo x > data/raw/a.csv"), cfg_over=over).action == "deny"
    assert g("Bash", bash("git push"), cfg_over=over).action == "ask"


def test_no_project_only_universal_rules(g, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert g("Bash", bash("git push"), cwd=plain, proj=None).action == "allow"
    assert g("Bash", bash("rm -rf /"), cwd=plain, proj=None).action == "deny"
