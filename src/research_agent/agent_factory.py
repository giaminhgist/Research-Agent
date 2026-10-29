"""Renders agents/*.md (Claude Code subagent files) from the agent registry."""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .agent_registry import AgentSpec, load_agents
from .skill_registry import SkillRegistry, default_invoke, load_catalog

# Spike (docs/SKILLS.md): subagents preload builtin, plugin and bare user skills listed in `skills:`.
BUILTIN_PRELOAD = True

DOMAIN_NOTE = (
    "## Domain notes\n\n"
    "Read the checklists that apply to the project before you start. They are in the Research-Agent plugin under "
    "`config/domain/`: `eye-tracking.md`, `medical-imaging.md`, `dementia-clinical.md`, "
    "`representation-learning.md`, `reporting-standards.md` (`ra status` prints the plugin path).\n"
)


def _invoke(sid: str, registry: SkillRegistry | None, catalog: dict) -> str:
    if registry is not None and (sk := registry.get(sid)) is not None and sk.installed:
        return sk.invoke_as
    return catalog.get(sid, {}).get("invoke_as", default_invoke(sid))


def render_agent(spec: AgentSpec, registry: SkillRegistry | None, protocol: str, body: str, catalog: dict | None = None) -> str:
    catalog = catalog if catalog is not None else load_catalog().get("skills", {})
    preload = [s for s in spec.core_skills if BUILTIN_PRELOAD or not s.startswith("builtin:")]
    via_tool = [s for s in spec.core_skills if s not in preload]
    lines = ["---", f"name: {spec.name}", f"description: {json.dumps(spec.description)}", f"tools: {', '.join(spec.tools)}", "skills:"]
    lines += [f"  - {_invoke(s, registry, catalog)}" for s in preload]
    lines += [f"model: {spec.model}", f"color: {spec.color}", "---", ""]
    out = "\n".join(lines) + "\n"
    out += f"{spec.role}\n\nResponsibilities:\n" + "".join(f"- {r}\n" for r in spec.responsibilities) + "\n"
    out += body.strip() + "\n\n"
    out += "## Borrowable skills\n\n"
    out += ("Load these with the Skill tool when a task calls for them. "
            f"`ra resolve \"<task>\" --agent {spec.name}` ranks them for a specific task and reports missing API keys or tools.\n\n")
    out += "".join(f"- `{_invoke(s, registry, catalog)}`\n" for s in via_tool + spec.borrow_skills) + "\n"
    out += DOMAIN_NOTE + "\n"
    out += "## Shared protocol\n\n" + protocol.strip() + "\n"
    return out


def build_all(out_dir: Path, registry: SkillRegistry | None = None, check: bool = False) -> list[str]:
    root = paths.plugin_root()
    protocol = (root / "config" / "protocol.md").read_text(encoding="utf-8")
    catalog = load_catalog().get("skills", {})
    out_dir = Path(out_dir)
    changed: list[str] = []
    for name, spec in load_agents().items():
        body = (root / "registry" / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        text = render_agent(spec, registry, protocol, body, catalog)
        target = out_dir / f"{name}.md"
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != text:
            changed.append(target.name)
            if not check:
                out_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8", newline="\n")
    return changed
