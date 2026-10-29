"""Chooses skills for one task: the agent's core skills plus scored borrowable skills and their dependencies."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .agent_registry import AgentSpec
from .skill_registry import SkillRegistry

_STOP = {"the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "from", "by", "this", "that", "is", "be"}


@dataclass
class Resolution:
    agent: str
    preload: list[str] = field(default_factory=list)
    borrowed: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9+.-]*", text.lower()) if t not in _STOP}


def resolve(task: str, agent: AgentSpec, registry: SkillRegistry, task_type: str | None = None,
            max_borrow: int = 4, env: Mapping | None = None) -> Resolution:
    env = os.environ if env is None else env
    res = Resolution(agent.name)
    for sid in agent.core_skills:
        ok, why = registry.available(sid, env)
        sk = registry.get(sid)
        if sk and sk.installed:
            res.preload.append(sk.invoke_as)
            if not ok:
                res.missing.append((sid, ", ".join(why)))
        else:
            res.missing.append((sid, ", ".join(why)))

    words = _tokens(task)
    candidates = list(dict.fromkeys(agent.borrow_skills + [
        s.id for s in registry.all() if task_type and task_type in s.task_types and s.id not in registry.unmapped
    ]))
    scored = []
    for sid in candidates:
        if sid in agent.core_skills:
            continue
        sk = registry.get(sid)
        if sk is None:
            continue
        keys = set(sk.tags) | set(sk.name.split("-"))
        hits = sorted(words & keys)
        score = 2 * len(hits) + (3 if task_type and task_type in sk.task_types else 0) + (1 if sid in agent.borrow_skills else 0)
        if score >= 2 and (hits or task_type in sk.task_types):
            reason = (f"keywords {hits}" if hits else "") + (f"; task_type {task_type}" if task_type in sk.task_types else "")
            scored.append((-score, sid, reason.strip("; ")))
    chosen = [(sid, why) for _, sid, why in sorted(scored)[:max_borrow]]

    for sid, why in chosen:
        ok, missing = registry.available(sid, env)
        if ok:
            res.borrowed.append((registry.get(sid).invoke_as, why))
        else:
            res.missing.append((sid, ", ".join(missing)))
    for dep in registry.dependency_closure([sid for sid, _ in chosen] + list(agent.core_skills)):
        sk = registry.get(dep)
        if sk is None or dep in agent.core_skills or any(dep == c for c, _ in chosen):
            continue
        if dep not in res.dependencies:
            res.dependencies.append(dep)
    return res
