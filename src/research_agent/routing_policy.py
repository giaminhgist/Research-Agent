"""Maps a task description to the agent that should do it."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import paths


@dataclass
class Route:
    agent: str
    task_type: str
    confidence: float
    rationale: str


def _rules(rules_path: Path | None) -> list[dict]:
    with Path(rules_path or paths.plugin_root() / "registry" / "routing.toml").open("rb") as fh:
        return tomllib.load(fh).get("rule", [])


def _hits(text: str, keywords: list[str]) -> list[str]:
    return [k for k in keywords if re.search(r"(?<![\w-])" + re.escape(k.lower()) + r"(?![\w-])", text)]


def route(task: str, task_type: str | None = None, author_agent: str | None = None, rules_path: Path | None = None) -> Route:
    rules = _rules(rules_path)
    text = task.lower()
    scored = [(len(h), -i, r, h) for i, r in enumerate(rules) if (h := _hits(text, r.get("keywords", [])))]
    review_rule = next((r for r in rules if r["task_type"] == "review"), {"agent": "reviewer", "task_type": "review"})

    if task_type == "review" or (scored and max(scored)[2]["task_type"] == "review"):
        n = len(_hits(text, review_rule.get("keywords", [])))
        note = f"; author {author_agent!r} excluded" if author_agent else ""
        return Route(review_rule["agent"], "review", max(n / (n + 1), 0.5),
                     f"review tasks always go to the independent reviewer in a fresh context{note}")

    if task_type:
        typed = [r for r in rules if r["task_type"] == task_type]
        if typed:
            h = _hits(text, typed[0].get("keywords", []))
            return Route(typed[0]["agent"], task_type, 1.0, f"explicit task_type {task_type!r}" + (f"; matched {h}" if h else ""))

    if not scored:
        return Route("orchestrator", "plan", 0.0, "no routing keyword matched; the orchestrator should plan or ask")
    n, _, rule, hits = max(scored)
    return Route(rule["agent"], rule["task_type"], round(n / (n + 1), 3), f"matched {hits}")
