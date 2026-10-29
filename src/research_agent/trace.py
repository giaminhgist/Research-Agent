"""Append-only audit trail: <project>/.research-agent/trace.jsonl."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import paths


def append(project: Path, event: str, **data) -> dict:
    rec = {"ts": time.time(), "event": event, **data}
    f = paths.state_dir(project) / "trace.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return rec


def read(project: Path) -> list[dict]:
    f = paths.state_dir(project) / "trace.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
