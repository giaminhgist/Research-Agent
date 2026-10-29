"""Minimal YAML-frontmatter reader for SKILL.md and agent files (stdlib only).

Supports `key: value`, quoted values, `>` / `|` block scalars and `- item` lists, which is
everything the skill and agent files we read actually use.
"""

from __future__ import annotations


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    return v


def parse(text: str) -> tuple[dict, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    meta: dict = {}
    block = [ln.rstrip("\r\n") for ln in lines[1:end]]
    i = 0
    while i < len(block):
        line = block[i]
        if not line.strip() or line.lstrip().startswith("#") or line[0] in " \t" or ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key, rest = key.strip(), rest.strip()
        i += 1
        if rest in (">", "|", ">-", "|-", ">+", "|+"):
            parts = []
            while i < len(block) and (not block[i].strip() or block[i][0] in " \t"):
                parts.append(block[i].strip())
                i += 1
            joiner = " " if rest.startswith(">") else "\n"
            meta[key] = joiner.join(p for p in parts if p) if joiner == " " else joiner.join(parts).strip("\n")
        elif rest == "":
            items = []
            while i < len(block) and block[i].strip().startswith("- "):
                items.append(_scalar(block[i].strip()[2:]))
                i += 1
            meta[key] = items if items else ""
        else:
            meta[key] = _scalar(rest)
    return meta, "".join(lines[end + 1:])
