"""Task state machine for orchestrated work: <project>/.research-agent/tasks/tasks.json."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import paths

STATES = ("planned", "dispatched", "artifact_ready", "in_review", "passed", "failed", "needs_approval", "done")
ALLOWED = {
    "planned": {"dispatched"},
    "dispatched": {"artifact_ready", "failed", "needs_approval"},
    "artifact_ready": {"in_review"},
    "in_review": {"passed", "failed"},
    "failed": {"dispatched"},
    "needs_approval": {"dispatched", "failed"},
    "passed": {"done"},
    "done": set(),
}


class TaskStore:
    def __init__(self, project: Path):
        self.file = paths.state_dir(project) / "tasks" / "tasks.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create(self, title: str, agent: str, task_type: str, artifact_dir: str | None = None, plan_id: str | None = None) -> dict:
        data = self._load()
        tid = f"T{len(data) + 1:03d}"
        while tid in data:
            tid = f"T{int(tid[1:]) + 1:03d}"
        now = time.time()
        task = {
            "id": tid, "title": title, "agent": agent, "task_type": task_type, "plan_id": plan_id,
            "artifact_dir": artifact_dir or f".research-agent/artifacts/{tid}", "state": "planned",
            "created": now, "history": [{"state": "planned", "ts": now, "note": ""}],
        }
        data[tid] = task
        self._save(data)
        return task

    def transition(self, task_id: str, new_state: str, note: str = "") -> dict:
        data = self._load()
        if task_id not in data:
            raise KeyError(task_id)
        task = data[task_id]
        if new_state not in STATES or new_state not in ALLOWED[task["state"]]:
            raise ValueError(f"{task_id}: illegal transition {task['state']} -> {new_state}")
        task["state"] = new_state
        task["history"].append({"state": new_state, "ts": time.time(), "note": note})
        self._save(data)
        return task

    def get(self, task_id: str) -> dict | None:
        return self._load().get(task_id)

    def list(self, state: str | None = None) -> list[dict]:
        return [t for t in self._load().values() if state is None or t["state"] == state]
