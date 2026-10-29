"""Builds a fake ~/.claude tree with a few plugin, user and project skills."""

import json
from pathlib import Path


def _skill(d: Path, name: str, desc: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\nbody\n", encoding="utf-8")


def make_claude_home(root: Path) -> Path:
    home = root / "claude"
    plugins = home / "plugins"
    aris = plugins / "cache" / "aris" / "aris" / "abc"
    for n in ["research-lit", "exa-search", "paper-writing", "paper-plan", "paper-slides"]:
        _skill(aris / "skills" / n, n, f"ARIS {n} skill")
    _skill(aris / "skills" / "skills-codex" / "research-lit", "research-lit", "codex mirror")
    (aris / "skills" / "shared-references").mkdir(parents=True)
    (aris / "tools").mkdir(parents=True)
    (aris / "tools" / "skill-groups.tsv").write_text(
        "# comment\n"
        "group\tpaper-core\tWriting\tdesc\n"
        "skill\tpaper-writing\tpaper-core\tpaper-plan\tworkflow 3\n"
        "skill\tpaper-plan\tpaper-core\t-\toutline\n"
        "skill\tresearch-lit\tlit-search\t-\tlit review\n",
        encoding="utf-8",
    )
    sp = plugins / "cache" / "claude-plugins-official" / "superpowers" / "7.0.1"
    _skill(sp / "skills" / "brainstorming", "brainstorming", "Use before creative work")
    hum = plugins / "cache" / "humanizer" / "humanizer" / "3.1.0"
    _skill(hum, "humanizer", "Remove signs of AI writing")
    _skill(home / "skills" / "deep-research", "deep-research", "Survey-grade report")
    _skill(home / "skills" / "my-own-skill", "my-own-skill", "personal")
    (plugins / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {
            "aris@aris": [{"scope": "user", "installPath": str(aris)}],
            "superpowers@claude-plugins-official": [{"scope": "user", "installPath": str(sp)}],
            "humanizer@humanizer": [{"scope": "user", "installPath": str(hum)}],
        },
    }), encoding="utf-8")
    return home
