"""Approval records for high-risk actions: requests (pending) and time-limited grants."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from . import paths


def _read_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class ApprovalStore:
    def __init__(self, project: Path):
        self.dir = paths.state_dir(project) / "approvals"

    @property
    def _pending(self) -> Path:
        return self.dir / "pending.jsonl"

    @property
    def _granted(self) -> Path:
        return self.dir / "granted.jsonl"

    def request(self, rule: str, target: str, reason: str, headless: bool = False) -> dict:
        rec = {"id": secrets.token_hex(4), "rule": rule, "target": target, "reason": reason, "ts": time.time(), "headless": headless}
        if not any(p["rule"] == rule and p["target"] == target for p in self.pending()):
            _append(self._pending, rec)
        if headless:
            md = self.dir / "pending.md"
            if not md.exists():
                md.parent.mkdir(parents=True, exist_ok=True)
                md.write_text("# Pending approvals (headless run)\n\nEach action below was denied automatically. Approve with the command shown, then re-run.\n\n", encoding="utf-8")
            with md.open("a", encoding="utf-8") as fh:
                fh.write(f"- [{time.strftime('%Y-%m-%d %H:%M')}] **{rule}**: `{target}` — {reason}\n  to approve (user only): `ra approve grant {rule} \"{target}\"`\n")
        return rec

    def grant(self, rule: str, target: str = "*", ttl_hours: float = 24, by: str = "user") -> dict:
        now = time.time()
        rec = {"rule": rule, "target": target, "granted_at": now, "expires": now + ttl_hours * 3600, "by": by}
        _append(self._granted, rec)
        keep = [p for p in self.pending() if not (p["rule"] == rule and target in ("*", p["target"]))]
        self.dir.mkdir(parents=True, exist_ok=True)
        self._pending.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in keep), encoding="utf-8")
        return rec

    def is_approved(self, rule: str, target: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return any(g["rule"] == rule and g["target"] in ("*", target) and g.get("expires", 0) > now for g in _read_jsonl(self._granted))

    def pending(self) -> list[dict]:
        return _read_jsonl(self._pending)
