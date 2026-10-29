"""Research / Coding / Full loops with stop conditions and per-iteration checkpoints."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, paths
from .budget import Budget

LOOPS = {
    "research": ["research", "methodology", "reviewer"],
    "coding": ["coding", "experiment", "reviewer"],
    "full": ["research", "methodology", "coding", "experiment", "reviewer"],
    "none": [],
}


class LoopController:
    def __init__(self, project: Path, cfg: dict | None = None):
        self.project = Path(project)
        self.cfg = cfg if cfg is not None else config.load(self.project)
        self.file = paths.state_dir(self.project) / "loop.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict) -> dict:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
        return st

    def start(self, goal: str, mode: str) -> dict:
        if mode not in LOOPS:
            raise ValueError(f"unknown loop mode {mode!r}; choose from {sorted(LOOPS)}")
        return self._save({"goal": goal, "mode": mode, "iteration": 1, "step_index": 0, "verdicts": [],
                           "consecutive_fails": 0, "passed": False, "must_fix": [], "done": mode == "none",
                           "started": time.time()})

    def next_step(self) -> dict | None:
        st = self._load()
        if not st or st.get("done"):
            return None
        steps = LOOPS[st["mode"]]
        if st["step_index"] >= len(steps):
            return None
        step = {"iteration": st["iteration"], "agent": steps[st["step_index"]], "must_fix": list(st["must_fix"])}
        st["step_index"] += 1
        self._save(st)
        return step

    def record_verdict(self, verdict: str, must_fix: list[str]) -> None:
        st = self._load()
        v = verdict.upper()
        if v not in ("PASS", "PASS_WITH_FIXES", "FAIL"):
            raise ValueError(f"unknown verdict {verdict!r}")
        st["verdicts"].append({"iteration": st["iteration"], "verdict": v, "must_fix": must_fix})
        st["passed"] = v == "PASS"
        st["consecutive_fails"] = st["consecutive_fails"] + 1 if v == "FAIL" else 0
        st["must_fix"] = list(must_fix)
        self._save(st)

    def should_stop(self, session_usd: float | None = None, budget: Budget | None = None) -> tuple[bool, str]:
        st = self._load()
        if not st:
            return True, "not_started"
        if st.get("passed"):
            return True, "reviewer_pass"
        if st["consecutive_fails"] >= int(config.get(self.cfg, "budget.max_consecutive_fails", 2)):
            return True, "consecutive_fails"
        if budget is not None and budget.check_dispatch("loop", session_usd)[0] == "deny":
            return True, "budget"
        if st["iteration"] > int(config.get(self.cfg, "budget.max_loop_iterations", 3)):
            return True, "max_iterations"
        return False, ""

    def checkpoint(self) -> Path:
        st = self._load()
        last = st["verdicts"][-1] if st.get("verdicts") else {}
        d = paths.state_dir(self.project) / "checkpoints"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"iter-{st['iteration']}.md"
        summary = Budget(self.project, self.cfg).summary()
        f.write_text(
            f"# Loop checkpoint — iteration {st['iteration']}\n\n"
            f"- Goal: {st['goal']}\n- Mode: {st['mode']} ({' -> '.join(LOOPS[st['mode']])})\n"
            f"- Verdict: {last.get('verdict', 'none')}\n- Consecutive FAILs: {st['consecutive_fails']}\n"
            f"- Project cost so far: ${summary['project_usd']:.2f}\n\n## MUST_FIX carried forward\n"
            + "".join(f"- {m}\n" for m in st["must_fix"]) + "\n", encoding="utf-8")
        st["iteration"] += 1
        st["step_index"] = 0
        self._save(st)
        stop, reason = self.should_stop()
        if stop:
            st["done"], st["stop_reason"] = True, reason
            self._save(st)
        return f

    def status(self) -> dict:
        st = self._load()
        if st:
            st["stop"] = dict(zip(("stop", "reason"), self.should_stop()))
        return st
