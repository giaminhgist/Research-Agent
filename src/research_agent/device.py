"""Compute device detection: cuda -> mps -> cpu. Never raises."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


_PROBE = ("import json, torch\n"
          "if torch.cuda.is_available(): print(json.dumps({'device': 'cuda', 'name': torch.cuda.get_device_name(0), 'count': torch.cuda.device_count()}))\n"
          "elif getattr(torch.backends, 'mps', None) is not None and torch.backends.mps.is_available(): print(json.dumps({'device': 'mps', 'name': 'Apple MPS', 'count': 1}))\n"
          "else: print(json.dumps({'device': 'cpu', 'name': 'cpu', 'count': 0}))\n")


def detect(python: str | None = None) -> dict:
    """Device as seen by `python` (the job's interpreter) or, by default, by this process."""
    if python and Path(python).resolve() != Path(sys.executable).resolve():
        try:
            out = subprocess.run([python, "-c", _PROBE], capture_output=True, text=True, timeout=120)
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return _smi_or_cpu()
    try:
        import torch  # noqa: PLC0415 - optional dependency

        if torch.cuda.is_available():
            return {"device": "cuda", "name": torch.cuda.get_device_name(0), "count": torch.cuda.device_count()}
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return {"device": "mps", "name": "Apple MPS", "count": 1}
        return {"device": "cpu", "name": "cpu", "count": 0}
    except Exception:
        pass
    return _smi_or_cpu()


def _smi_or_cpu() -> dict:
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=10).stdout
            gpus = [l for l in out.splitlines() if l.startswith("GPU")]
            if gpus:
                return {"device": "cuda", "name": gpus[0].split(":", 1)[1].split("(")[0].strip(), "count": len(gpus)}
        except (OSError, subprocess.SubprocessError):
            pass
    return {"device": "cpu", "name": "cpu", "count": 0}
