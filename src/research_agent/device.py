"""Compute device detection: cuda -> mps -> cpu. Never raises."""

from __future__ import annotations

import shutil
import subprocess


def detect() -> dict:
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
