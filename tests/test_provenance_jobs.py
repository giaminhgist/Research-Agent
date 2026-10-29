import builtins
import json
import subprocess
import sys

from research_agent import config, device, jobs, provenance
from research_agent.budget import Budget


def git_repo(project):
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=project, check=True)


def test_capture_manifest_fields(project):
    git_repo(project)
    (project / "data/raw/a.csv").write_text("1,2\n")
    cfgf = project / "cfg.yaml"
    cfgf.write_text("lr: 0.1\n")
    rid = provenance.capture(project, ["python", "train.py"], seed=7, config_paths=[cfgf], data_paths=[project / "data/raw"])
    m = json.loads((project / ".research-agent/runs" / rid / "manifest.json").read_text())
    assert rid.startswith("R") and m["run_id"] == rid and m["seed"] == 7
    assert len(m["git"]["sha"]) == 40 and m["git"]["dirty"] is True
    assert set(m["data"]) == {"data/raw"} and len(m["data"]["data/raw"]["sha256"]) == 64
    assert "cfg.yaml" in m["config"] and m["env"]["python"]
    assert m["device"]["device"] in ("cpu", "cuda", "mps")
    assert (project / ".research-agent/runs" / rid / "pip_freeze.txt").exists()
    assert provenance.exists(project, rid) and not provenance.exists(project, "R0")


def test_capture_outside_git(project):
    rid = provenance.capture(project, ["echo"], None, [], [])
    assert json.loads((project / ".research-agent/runs" / rid / "manifest.json").read_text())["git"] is None


def test_finalize_and_list(project):
    rid = provenance.capture(project, ["echo"], None, [], [])
    mfile = project / "metrics.json"
    mfile.write_text('{"auc": 0.81}')
    m = provenance.finalize(project, rid, 0, mfile)
    assert m["exit_code"] == 0 and m["metrics"] == {"auc": 0.81}
    assert [r["run_id"] for r in provenance.list_runs(project)] == [rid]


def test_job_runs_cpu_command(project):
    r = jobs.run_job(project, [sys.executable, "-c", "import os; print(1, os.environ['RA_SEED'])"], seed=3)
    assert r["status"] == "ok" and r["exit_code"] == 0
    assert "1 3" in (project / ".research-agent/runs" / r["run_id"] / "log.txt").read_text()
    assert provenance.exists(project, r["run_id"])


def test_job_failure_recorded(project):
    r = jobs.run_job(project, [sys.executable, "-c", "raise SystemExit(4)"])
    assert r["status"] == "failed" and r["exit_code"] == 4


def test_job_blocked_over_gpu_cap(project):
    r = jobs.run_job(project, [sys.executable, "-c", "print(1)"], gpu_hours=10)
    assert r["status"] == "blocked" and "run_id" not in r or r.get("run_id") is None
    assert not (project / ".research-agent/runs").exists() or not any((project / ".research-agent/runs").iterdir())


def test_job_gpu_cost_recorded(project):
    r = jobs.run_job(project, [sys.executable, "-c", "print(1)"], gpu_hours=1)
    assert r["status"] == "ok"
    recs = [json.loads(l) for l in (project / ".research-agent/budget.jsonl").read_text().splitlines()]
    gpu = [x for x in recs if x["kind"] == "gpu_job"]
    assert gpu[0]["id"] == r["run_id"] and 0 < gpu[0]["detail"]["gpu_hours"] <= 1


def test_job_timeout(project, monkeypatch):
    monkeypatch.setattr(Budget, "check_gpu_job", lambda self, h: (True, 0.1, 1))
    r = jobs.run_job(project, [sys.executable, "-c", "import time; time.sleep(5)"], gpu_hours=0.01)
    assert r["status"] == "timeout"


def test_device_cpu_fallback(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "torch":
            raise ImportError
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(device.shutil, "which", lambda _: None)
    assert device.detect() == {"device": "cpu", "name": "cpu", "count": 0}
