"""Three-tier budget: USD per session, USD per project, GPU USD per job.

Ledger: <project>/.research-agent/budget.jsonl with lines
{"ts", "kind": "session" | "gpu_job", "id", "usd", "detail"}. For sessions the latest line per id wins.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, paths

FAMILIES = ("opus", "sonnet", "haiku")


def session_cost_from_transcript(path: Path, pricing: dict) -> float | None:
    """USD cost of a Claude Code transcript (JSONL), or None if it cannot be read."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return None
    usage_by_msg: dict[str, tuple[str, dict]] = {}
    for i, line in enumerate(text.splitlines()):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
            continue
        usage_by_msg[str(msg.get("id") or f"line{i}")] = (str(msg.get("model", "")), msg["usage"])
    total = 0.0
    for model, u in usage_by_msg.values():
        fam = next((f for f in FAMILIES if f in model.lower()), "sonnet")
        rate = pricing.get(fam, {})
        total += (
            u.get("input_tokens", 0) * rate.get("input", 0)
            + u.get("output_tokens", 0) * rate.get("output", 0)
            + u.get("cache_creation_input_tokens", 0) * rate.get("cache_write", 0)
            + u.get("cache_read_input_tokens", 0) * rate.get("cache_read", 0)
        ) / 1e6
    return round(total, 6)


class Budget:
    def __init__(self, project: Path, cfg: dict | None = None):
        self.project = Path(project)
        self.cfg = cfg if cfg is not None else config.load(self.project)
        self.ledger = paths.state_dir(self.project) / "budget.jsonl"

    def _b(self, key: str) -> float:
        return float(config.get(self.cfg, f"budget.{key}", 0) or 0)

    def _records(self) -> list[dict]:
        if not self.ledger.is_file():
            return []
        out = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def _append(self, kind: str, rid: str, usd: float, detail: dict | None = None) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "kind": kind, "id": rid, "usd": round(usd, 6), "detail": detail or {}}) + "\n")

    def record_session(self, session_id: str, usd: float) -> None:
        self._append("session", session_id, usd)

    def _sessions(self) -> dict[str, float]:
        latest: dict[str, float] = {}
        for r in self._records():
            if r.get("kind") == "session":
                latest[r["id"]] = float(r.get("usd", 0))
        return latest

    def _gpu_usd(self) -> float:
        return sum(float(r.get("usd", 0)) for r in self._records() if r.get("kind") == "gpu_job")

    def project_total(self, override: tuple[str, float] | None = None) -> float:
        sessions = self._sessions()
        if override is not None:
            sessions[override[0]] = override[1]
        return round(sum(sessions.values()) + self._gpu_usd(), 6)

    def check_dispatch(self, session_id: str, session_usd: float | None) -> tuple[str, str]:
        s_cap, p_cap, warn = self._b("max_usd_per_session"), self._b("max_usd_per_project"), self._b("warn_fraction") or 0.8
        p_total = self.project_total(override=(session_id, session_usd) if session_usd is not None else None)
        if session_usd is not None and s_cap and session_usd >= s_cap:
            return "deny", f"session cost ${session_usd:.2f} reached max_usd_per_session ${s_cap:.2f}"
        if p_cap and p_total >= p_cap:
            return "deny", f"project cost ${p_total:.2f} reached max_usd_per_project ${p_cap:.2f}"
        notes = []
        if session_usd is None:
            notes.append("session cost unknown (transcript unreadable)")
        elif s_cap and session_usd >= warn * s_cap:
            notes.append(f"session at ${session_usd:.2f} of ${s_cap:.2f}")
        if p_cap and p_total >= warn * p_cap:
            notes.append(f"project at ${p_total:.2f} of ${p_cap:.2f}")
        return ("warn", "; ".join(notes)) if notes else ("allow", "")

    def check_gpu_job(self, gpu_hours: float) -> tuple[bool, float, int]:
        rate, cap = self._b("gpu_usd_per_hour"), self._b("max_gpu_usd_per_job")
        est = round(gpu_hours * rate, 6)
        if gpu_hours <= 0:
            return True, 0.0, 0
        timeout = int(min(gpu_hours, cap / rate if rate else gpu_hours) * 3600)
        return est <= cap, est, timeout

    def record_gpu_job(self, job_id: str, gpu_hours: float) -> float:
        usd = round(gpu_hours * self._b("gpu_usd_per_hour"), 6)
        self._append("gpu_job", job_id, usd, {"gpu_hours": gpu_hours})
        return usd

    def summary(self) -> dict:
        sessions = self._sessions()
        return {
            "sessions": len(sessions),
            "session_usd": round(sum(sessions.values()), 4),
            "gpu_usd": round(self._gpu_usd(), 4),
            "project_usd": self.project_total(),
            "caps": {k: self._b(k) for k in ("max_usd_per_session", "max_usd_per_project", "max_gpu_usd_per_job", "gpu_usd_per_hour")},
        }
