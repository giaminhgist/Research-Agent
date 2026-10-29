"""Run manifests: everything needed to reproduce a result (<project>/.research-agent/runs/<run_id>/)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from pathlib import Path

from . import device, paths

BIG_FILE = 1 << 30  # files above 1 GB are fingerprinted by size + mtime


def _sha_file(p: Path) -> tuple[str, bool]:
    st = p.stat()
    if st.st_size > BIG_FILE:
        return hashlib.sha256(f"{st.st_size}:{st.st_mtime}".encode()).hexdigest(), True
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest(), False


def hash_path(p: Path) -> dict:
    p = Path(p)
    if p.is_file():
        digest, fast = _sha_file(p)
        return {"sha256": digest, "files": 1, "fast_hash": fast}
    h, n, fast_any = hashlib.sha256(), 0, False
    for f in sorted(x for x in p.rglob("*") if x.is_file()):
        digest, fast = _sha_file(f)
        h.update(f.relative_to(p).as_posix().encode() + b"\0" + digest.encode() + b"\n")
        n += 1
        fast_any |= fast
    return {"sha256": h.hexdigest(), "files": n, "fast_hash": fast_any}


def _rel(p: Path, project: Path) -> str:
    try:
        return Path(p).resolve().relative_to(Path(project).resolve()).as_posix()
    except ValueError:
        return str(Path(p).resolve())


def _git(project: Path) -> dict | None:
    def run(*args):
        return subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, timeout=60)

    try:
        head = run("rev-parse", "HEAD")
        if head.returncode != 0:
            return None
        status = run("status", "--porcelain", "--", ".", ":(exclude).research-agent").stdout
        diff = run("diff", "HEAD", "--", ".", ":(exclude).research-agent").stdout
        return {"sha": head.stdout.strip(), "dirty": bool(status.strip()), "diff_sha256": hashlib.sha256(diff.encode()).hexdigest()}
    except (OSError, subprocess.SubprocessError):
        return None


def runs_dir(project: Path) -> Path:
    return paths.state_dir(project) / "runs"


def capture(project: Path, cmd: list[str], seed: int | None, config_paths: list[Path], data_paths: list[Path]) -> str:
    project = Path(project)
    rid = f"R{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    d = runs_dir(project) / rid
    d.mkdir(parents=True)
    try:
        freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        freeze = f"# pip freeze failed: {exc}\n"
    (d / "pip_freeze.txt").write_text(freeze, encoding="utf-8")
    manifest = {
        "run_id": rid,
        "cmd": list(cmd),
        "cwd": str(project),
        "git": _git(project),
        "data": {_rel(p, project): hash_path(p) for p in data_paths},
        "config": {_rel(p, project): hash_path(p)["sha256"] for p in config_paths},
        "seed": seed,
        "env": {"python": sys.version.split()[0], "platform": platform.platform(), "executable": sys.executable,
                "pip_freeze_sha256": hashlib.sha256(freeze.encode()).hexdigest(),
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")},
        "device": device.detect(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return rid


def finalize(project: Path, run_id: str, exit_code: int, metrics_path: Path | None = None, status: str | None = None) -> dict:
    f = runs_dir(project) / run_id / "manifest.json"
    m = json.loads(f.read_text(encoding="utf-8"))
    m["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    m["exit_code"] = exit_code
    if status:
        m["status"] = status
    if metrics_path and Path(metrics_path).is_file():
        try:
            m["metrics"] = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
        except ValueError:
            m["metrics_file"] = str(metrics_path)
    f.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def exists(project: Path, run_id: str) -> bool:
    return bool(run_id) and "/" not in run_id and "\\" not in run_id and (runs_dir(project) / run_id / "manifest.json").is_file()


def list_runs(project: Path) -> list[dict]:
    d = runs_dir(project)
    out = []
    for f in sorted(d.glob("*/manifest.json")) if d.is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return out
