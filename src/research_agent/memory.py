"""Project memory: decisions (ADR style), progress notes and a small state dict."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import paths


class ProjectMemory:
    def __init__(self, project: Path):
        self.dir = paths.state_dir(project) / "memory"

    def _log(self, kind: str, **data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "kind": kind, **data}, ensure_ascii=False) + "\n")

    def _entries(self, kind: str) -> list[dict]:
        f = self.dir / "log.jsonl"
        if not f.is_file():
            return []
        out = []
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") == kind:
                out.append(rec)
        return out

    def decide(self, title: str, decision: str, rationale: str, alternatives: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        date = time.strftime("%Y-%m-%d %H:%M")
        block = f"## {title}\n- Date: {date}\n- Decision: {decision}\n- Rationale: {rationale}\n"
        if alternatives:
            block += f"- Alternatives considered: {alternatives}\n"
        with (self.dir / "decisions.md").open("a", encoding="utf-8") as fh:
            fh.write(block + "\n")
        self._log("decision", title=title, decision=decision, rationale=rationale, alternatives=alternatives)

    def progress(self, note: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "progress.md").open("a", encoding="utf-8") as fh:
            fh.write(f"- [{time.strftime('%Y-%m-%d %H:%M')}] {note}\n")
        self._log("progress", note=note)

    def state(self) -> dict:
        f = self.dir / "state.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def update_state(self, **kv) -> dict:
        st = {**self.state(), **kv}
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "state.json").write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
        return st

    def summary(self, max_chars: int = 1500) -> str:
        lines = []
        decisions = self._entries("decision")[-5:]
        if decisions:
            lines.append("Recent decisions:")
            lines += [f"- {d['title']}: {d['decision']}" for d in decisions]
        prog = self._entries("progress")[-5:]
        if prog:
            lines.append("Recent progress:")
            lines += [f"- {p['note']}" for p in prog]
        st = self.state()
        if st:
            lines.append("State: " + ", ".join(f"{k}={v}" for k, v in st.items()))
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
