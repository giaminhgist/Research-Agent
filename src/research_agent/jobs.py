"""Budgeted, provenance-tracked job runner behind `ra job run`."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, provenance, trace
from .budget import Budget


def run_job(project: Path, cmd: list[str], gpu_hours: float = 0.0, seed: int | None = None, configs=(), data=(),
            cfg: dict | None = None, metrics: Path | None = None, echo: bool = True) -> dict:
    project = Path(project)
    cfg = cfg if cfg is not None else config.load(project)
    budget = Budget(project, cfg)
    timeout_s = 0
    if gpu_hours > 0:
        ok, est, timeout_s = budget.check_gpu_job(gpu_hours)
        if not ok:
            cap = config.get(cfg, "budget.max_gpu_usd_per_job")
            return {"status": "blocked", "run_id": None, "est_usd": est,
                    "reason": f"estimated ${est:.2f} exceeds max_gpu_usd_per_job ${cap}; get approval and raise the cap"}
    rid = provenance.capture(project, cmd, seed, [Path(c) for c in configs], [Path(d) for d in data])
    env = {**os.environ, "RA_RUN_ID": rid, "RA_RUN_DIR": str(provenance.runs_dir(project) / rid)}
    if seed is not None:
        env.update(RA_SEED=str(seed), PYTHONHASHSEED=str(seed))
    log = provenance.runs_dir(project) / rid / "log.txt"
    start = time.time()
    status = "ok"
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")

        def pump():
            for line in proc.stdout:
                fh.write(line)
                if echo:
                    sys.stdout.write(line)

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        try:
            proc.wait(timeout=timeout_s or None)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            status = "timeout"
        t.join(timeout=5)
    code = proc.returncode
    if status == "ok" and code != 0:
        status = "failed"
    provenance.finalize(project, rid, code, metrics, status=status)
    if gpu_hours > 0:
        budget.record_gpu_job(rid, min(gpu_hours, (time.time() - start) / 3600))
    trace.append(project, "job.run", run_id=rid, status=status, exit_code=code, gpu_hours=gpu_hours)
    return {"status": status, "run_id": rid, "exit_code": code}
