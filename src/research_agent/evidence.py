"""Evidence lint: every claim bullet must say whether it is sourced, from a run, inferred or a hypothesis."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

CLAIM_HEADINGS = re.compile(r"^#{1,6}\s+.*\b(claims?|findings?|results?|conclusions?|key points?)\b", re.I)
HEADING = re.compile(r"^#{1,6}\s+")
BULLET = re.compile(r"^\s*[-*]\s+\S")
SOURCED = re.compile(r"\[SOURCED:([^\]]+)\]")
RUN = re.compile(r"\[RUN:([^\]]+)\]")
LABEL = re.compile(r"\[(SOURCED:[^\]]+|RUN:[^\]]+|INFERRED|HYPOTHESIS)\]")


@dataclass
class Issue:
    line: int
    kind: str
    msg: str


def lint(text: str, known_keys: set[str], run_exists: Callable[[str], bool]) -> list[Issue]:
    issues: list[Issue] = []
    in_claims = in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if HEADING.match(line):
            in_claims = bool(CLAIM_HEADINGS.match(line))
            continue
        if not in_claims or not BULLET.match(line):
            continue
        if not LABEL.search(line):
            issues.append(Issue(n, "unlabelled", f"claim has no evidence label: {line.strip()[:80]}"))
            continue
        for group in SOURCED.findall(line):
            for key in (k.strip() for k in group.split(",")):
                if key and key not in known_keys:
                    issues.append(Issue(n, "unknown-source", f"source key {key!r} is not in the bibliography or KB"))
        for group in RUN.findall(line):
            for rid in (r.strip() for r in group.split(",")):
                if rid and not run_exists(rid):
                    issues.append(Issue(n, "unknown-run", f"run {rid!r} has no manifest"))
    return issues
