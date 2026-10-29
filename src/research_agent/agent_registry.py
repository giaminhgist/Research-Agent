"""Loads and validates registry/agents.toml, the source of truth for the seven agents."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .skill_registry import load_catalog

AGENT_NAMES = ("orchestrator", "research", "methodology", "coding", "experiment", "writing", "reviewer")
KNOWN_TOOLS = {
    "Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill", "Agent", "AskUserQuestion",
    "WebSearch", "WebFetch", "TodoWrite", "NotebookEdit",
}
MODEL_ALIASES = {"opus", "sonnet", "haiku", "inherit"}


class RegistryError(Exception):
    pass


@dataclass
class AgentSpec:
    name: str
    role: str
    description: str
    model: str
    color: str
    tools: list[str]
    core_skills: list[str]
    borrow_skills: list[str]
    responsibilities: list[str]
    write_scope: list[str] | None = field(default=None)


def default_agents_path() -> Path:
    return paths.plugin_root() / "registry" / "agents.toml"


def load_agents(path: Path | None = None, catalog_ids: set[str] | None = None) -> dict[str, AgentSpec]:
    with Path(path or default_agents_path()).open("rb") as fh:
        raw = tomllib.load(fh).get("agents", {})
    agents: dict[str, AgentSpec] = {}
    errors: list[str] = []
    for name, d in raw.items():
        try:
            agents[name] = AgentSpec(
                name=name,
                role=d.get("role", ""),
                description=d.get("description", ""),
                model=d.get("model", ""),
                color=d.get("color", ""),
                tools=list(d.get("tools", [])),
                core_skills=list(d.get("core_skills", [])),
                borrow_skills=list(d.get("borrow_skills", [])),
                responsibilities=list(d.get("responsibilities", [])),
                write_scope=d.get("write_scope"),
            )
        except (TypeError, AttributeError) as exc:
            errors.append(f"{name}: malformed entry ({exc})")
    if catalog_ids is None:
        catalog_ids = set(load_catalog().get("skills", {}))
    errors += validate(agents, catalog_ids)
    if errors:
        raise RegistryError("; ".join(errors))
    return agents


def validate(agents: dict[str, AgentSpec], catalog_ids: set[str]) -> list[str]:
    errs: list[str] = []
    if set(agents) != set(AGENT_NAMES):
        errs.append(f"agents must be exactly {AGENT_NAMES}, got {tuple(sorted(agents))}")
    for a in agents.values():
        if not (a.model in MODEL_ALIASES or a.model.startswith("claude-")):
            errs.append(f"{a.name}: unknown model {a.model!r}")
        for t in a.tools:
            if t not in KNOWN_TOOLS and not t.startswith("mcp__"):
                errs.append(f"{a.name}: unknown tool {t!r}")
        for sid in a.core_skills + a.borrow_skills:
            if sid not in catalog_ids:
                errs.append(f"{a.name}: skill {sid!r} not in catalog")
        if not 1 <= len(a.core_skills) <= 12:
            errs.append(f"{a.name}: needs 1-12 core skills, has {len(a.core_skills)}")
        both = set(a.core_skills) & set(a.borrow_skills)
        if both:
            errs.append(f"{a.name}: skills both core and borrow: {sorted(both)}")
        if len(set(a.core_skills)) != len(a.core_skills):
            errs.append(f"{a.name}: duplicate core skills")
        if not a.role.startswith("You are"):
            errs.append(f"{a.name}: role must start with 'You are'")
    return errs
