"""Quality gates: an artifact is accepted on evidence, never on the author's say-so."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import evidence, kb, paths, provenance
from .tasks import TaskStore

VERDICT = re.compile(r"^\s*VERDICT:\s*(PASS_WITH_FIXES|PASS|FAIL)\b", re.M)
HANDOFF = re.compile(r"```handoff\s*\n(.*?)```", re.S)


@dataclass
class GateReport:
    task_id: str
    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)


def parse_handoff(text: str) -> dict | None:
    m = HANDOFF.search(text)
    if not m:
        return None
    out: dict = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0].rstrip()
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            out[k.strip()] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            out[k.strip()] = v.strip("'\"")
    return out


def review_verdict(project: Path, task_id: str) -> str | None:
    f = paths.state_dir(project) / "reviews" / f"{task_id}.md"
    if not f.is_file():
        return None
    m = VERDICT.search(f.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def check(project: Path, task_id: str, stage: str = "final") -> GateReport:
    project = Path(project)
    rep = GateReport(task_id, False)
    task = TaskStore(project).get(task_id)
    if task is None:
        rep.checks.append(("task", False, f"unknown task {task_id}"))
        return rep
    adir = project / task["artifact_dir"]
    files = [f for f in adir.rglob("*") if f.is_file()] if adir.is_dir() else []
    rep.checks.append(("artifact_exists", bool(files), f"{len(files)} file(s) in {task['artifact_dir']}"))

    md = [f for f in files if f.suffix == ".md"]
    handoff = next((h for f in md if (h := parse_handoff(f.read_text(encoding="utf-8", errors="replace"))) and h.get("status")), None)
    rep.checks.append(("handoff", handoff is not None, "handoff block found" if handoff else "no ```handoff block with a status"))

    claims = [project / handoff["claims_file"]] if handoff and handoff.get("claims_file") else md
    keys = kb.bib_keys(project)
    issues = []
    for f in claims:
        if f.is_file():
            issues += [f"{f.name}:{i.line} {i.kind}: {i.msg}" for i in evidence.lint(f.read_text(encoding="utf-8", errors="replace"), keys, lambda r: provenance.exists(project, r))]
    rep.checks.append(("evidence", not issues, "; ".join(issues[:10]) if issues else "all claims labelled and resolvable"))

    run_ids = (handoff or {}).get("run_ids") or []
    if isinstance(run_ids, str):
        run_ids = [run_ids] if run_ids else []
    bad = [r for r in run_ids if not provenance.exists(project, r)]
    rep.checks.append(("runs", not bad, f"missing manifests: {bad}" if bad else f"{len(run_ids)} run(s) resolvable"))

    if stage == "final":
        v = review_verdict(project, task_id)
        rep.checks.append(("review", v in ("PASS", "PASS_WITH_FIXES"), f"reviewer verdict: {v or 'none'}"))
    rep.passed = all(ok for _, ok, _ in rep.checks)
    return rep
