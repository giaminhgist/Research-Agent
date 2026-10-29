"""Discovers installed skills and merges them with the curated catalog.

Sources, in order: installed plugins (~/.claude/plugins/installed_plugins.json), user skills
(~/.claude/skills), project skills (<project>/.claude/skills) and Claude Code builtins (catalog only).
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter, paths

REPO_OF_PLUGIN = {
    "superpowers": "superpowers",
    "aris": "aris",
    "humanizer": "humanizer",
    "supervisor-skills": "supervisor-skills",
}
# Repos whose skills are installed user-level (bare names) by their upstream instructions.
USER_LEVEL_REPOS = {"supervisor-skills"}


@dataclass
class Skill:
    id: str
    name: str
    source: str
    invoke_as: str
    description: str = ""
    path: Path | None = None
    installed: bool = False
    tags: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    requires_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


def default_catalog_path() -> Path:
    return paths.plugin_root() / "registry" / "skills_catalog.toml"


def load_catalog(path: Path | None = None) -> dict:
    with Path(path or default_catalog_path()).open("rb") as fh:
        return tomllib.load(fh)


def default_invoke(skill_id: str) -> str:
    repo, _, name = skill_id.partition(":")
    return name if repo in USER_LEVEL_REPOS | {"builtin", "user", "project"} else skill_id


def _read_skill(skill_md: Path) -> tuple[str, str]:
    try:
        meta, _ = frontmatter.parse(skill_md.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        meta = {}
    return str(meta.get("name") or skill_md.parent.name), str(meta.get("description") or "")


def _skill_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("skills-codex") and (d / "SKILL.md").is_file())


class SkillRegistry:
    def __init__(self, skills: dict[str, Skill], unmapped: list[str] | None = None):
        self._skills = skills
        self.unmapped = list(unmapped or [])

    # ---- construction ------------------------------------------------------------------------------------------
    @classmethod
    def discover(cls, claude_home: Path | None = None, project: Path | None = None, catalog_path: Path | None = None) -> "SkillRegistry":
        claude_home = Path(claude_home or paths.claude_home())
        catalog = load_catalog(catalog_path)
        cat_skills: dict = catalog.get("skills", {})
        user_level_names = {i.split(":", 1)[1]: i for i in cat_skills if i.split(":", 1)[0] in USER_LEVEL_REPOS}
        found: dict[str, Skill] = {}
        aris_roots: list[Path] = []

        for plugin_id, install_path in _installed_plugins(claude_home):
            pname = plugin_id.split("@", 1)[0]
            source = REPO_OF_PLUGIN.get(pname, pname)
            root = Path(install_path)
            if source == "aris":
                aris_roots.append(root)
            dirs = _skill_dirs(root / "skills")
            if (root / "SKILL.md").is_file():
                dirs.append(root)
            for d in dirs:
                name, desc = _read_skill(d / "SKILL.md")
                sid = f"{source}:{name}"
                found.setdefault(sid, Skill(sid, name, source, f"{pname}:{name}", desc, d, True))

        for scope, root in (("user", claude_home / "skills"), ("project", Path(project) / ".claude" / "skills" if project else None)):
            for d in _skill_dirs(root) if root else []:
                name, desc = _read_skill(d / "SKILL.md")
                if scope == "user" and name in user_level_names:
                    sid = user_level_names[name]
                    source = sid.split(":", 1)[0]
                else:
                    sid, source = f"{scope}:{name}", scope
                found.setdefault(sid, Skill(sid, name, source, name, desc, d, True))

        for sid, meta in cat_skills.items():
            repo, _, name = sid.partition(":")
            sk = found.get(sid)
            if sk is None:
                builtin = meta.get("source") == "builtin" or repo == "builtin"
                sk = Skill(sid, name, repo, meta.get("invoke_as", default_invoke(sid)), installed=builtin)
                found[sid] = sk
            sk.description = sk.description or meta.get("description", "")
            sk.tags = list(meta.get("tags", []))
            sk.task_types = list(meta.get("task_types", []))
            sk.requires_env = list(meta.get("requires_env", []))
            sk.requires_tools = list(meta.get("requires_tools", []))
            sk.depends_on = list(meta.get("depends_on", []))

        for root in aris_roots:
            for name, requires in _aris_requires(root / "tools" / "skill-groups.tsv").items():
                sk = found.get(f"aris:{name}")
                if sk:
                    sk.depends_on.extend(r for r in requires if r not in sk.depends_on)

        return cls(found, catalog.get("unmapped", {}).get("ids", []))

    # ---- queries -----------------------------------------------------------------------------------------------
    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.id)

    def get(self, key: str) -> Skill | None:
        if key in self._skills:
            return self._skills[key]
        by_invoke = [s for s in self._skills.values() if s.invoke_as == key]
        if len(by_invoke) == 1:
            return by_invoke[0]
        by_name = [s for s in self._skills.values() if s.name == key]
        return by_name[0] if len(by_name) == 1 else None

    def counts_by_source(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self._skills.values():
            if s.installed:
                out[s.source] = out.get(s.source, 0) + 1
        return out

    def available(self, key: str, env: Mapping | None = None) -> tuple[bool, list[str]]:
        env = os.environ if env is None else env
        s = self.get(key)
        if s is None:
            return False, ["unknown skill"]
        if not s.installed:
            return False, ["not installed"]
        missing = [f"env:{k}" for k in s.requires_env if not env.get(k)]
        missing += [f"tool:{t}" for t in s.requires_tools if shutil.which(t) is None]
        return (not missing), missing

    def dependency_closure(self, ids: list[str]) -> list[str]:
        """Skills plus everything they require, dependencies first, cycle-safe."""
        order: list[str] = []
        visiting: set[str] = set()

        def visit(sid: str) -> None:
            if sid in order or sid in visiting:
                return
            visiting.add(sid)
            s = self.get(sid)
            for dep in (s.depends_on if s else []):
                visit(dep)
            visiting.discard(sid)
            order.append(s.id if s else sid)

        for sid in ids:
            visit(sid)
        return order


def _installed_plugins(claude_home: Path) -> list[tuple[str, str]]:
    f = claude_home / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for pid, entries in (data.get("plugins") or {}).items():
        for e in entries if isinstance(entries, list) else [entries]:
            if isinstance(e, dict) and e.get("installPath"):
                out.append((pid, e["installPath"]))
                break
    return out


def _aris_requires(tsv: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    try:
        lines = tsv.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        cols = line.split("\t")
        if len(cols) >= 4 and cols[0] == "skill":
            req = cols[3].strip()
            out[cols[1]] = [] if req in ("", "-") else [f"aris:{r.strip()}" for r in req.split(",") if r.strip()]
    return out


def installed_plugin_ids(claude_home: Path | None = None) -> list[str]:
    return [pid for pid, _ in _installed_plugins(Path(claude_home or paths.claude_home()))]
