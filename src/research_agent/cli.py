"""`ra`: the Research-Agent command line used by agents, hooks and people."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from . import config, gates, kb, paths, provenance


def _print(data, as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human if human is not None else json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _project() -> Path | None:
    return paths.find_project_root(Path.cwd())


def _need_project() -> Path:
    p = _project()
    if p is None:
        print("Not inside a Research-Agent project. Run `ra init` in the project directory first.", file=sys.stderr)
        raise SystemExit(2)
    return p


# ---- commands --------------------------------------------------------------------------------------------------------
def cmd_setup(a):
    from .setup import setup_machine
    for line in setup_machine(a.reviewer):
        print(f"- {line}")
    return 0


def cmd_init(a):
    from .setup import init_project
    cfg = config.load(None)
    state = init_project(Path.cwd(), a.protected, a.sensitive, a.irb,
                         a.budget_session if a.budget_session is not None else config.get(cfg, "budget.max_usd_per_session", 10.0),
                         a.budget_project if a.budget_project is not None else config.get(cfg, "budget.max_usd_per_project", 100.0),
                         reviewer=config.get(cfg, "reviewer.backend", "claude"))
    print(f"Research-Agent project initialised: {state}")
    print("Edit .research-agent/project.toml to declare raw-data (protected) and sensitive paths and budgets.")
    return 0


def cmd_doctor(a):
    from .doctor import run
    checks = run(skills=a.skills, live=a.live)
    if a.json:
        _print([dataclasses.asdict(c) for c in checks], True)
    else:
        for c in checks:
            mark = "ok  " if c.ok else ("WARN" if c.level == "warn" else "FAIL")
            print(f"[{mark}] {c.name}: {c.detail}")
    return 0 if all(c.ok or c.level == "warn" for c in checks) else 1


def cmd_route(a):
    from .routing_policy import route
    r = route(a.task, task_type=a.type, author_agent=a.author)
    _print(dataclasses.asdict(r), a.json, f"{r.agent} ({r.task_type}, confidence {r.confidence}): {r.rationale}")
    return 0


def cmd_resolve(a):
    from .agent_registry import load_agents
    from .skill_registry import SkillRegistry
    from .skill_resolver import resolve
    agents = load_agents()
    if a.agent not in agents:
        print(f"unknown agent {a.agent!r}; choose from {sorted(agents)}", file=sys.stderr)
        return 2
    res = resolve(a.task, agents[a.agent], SkillRegistry.discover(project=_project()), task_type=a.type, max_borrow=a.max)
    if a.json:
        _print(dataclasses.asdict(res), True)
    else:
        print(f"agent: {res.agent}\npreload: {', '.join(res.preload)}")
        print("borrow: " + ("; ".join(f"{s} ({why})" for s, why in res.borrowed) or "-"))
        print("dependencies: " + (", ".join(res.dependencies) or "-"))
        print("missing: " + ("; ".join(f"{s} ({why})" for s, why in res.missing) or "-"))
    return 0


def cmd_agents(a):
    from .agent_factory import build_all
    from .skill_registry import SkillRegistry
    out_dir = paths.plugin_root() / "agents"
    if a.action == "show":
        f = out_dir / f"{a.name}.md"
        if not f.is_file():
            print(f"unknown agent {a.name!r}", file=sys.stderr)
            return 2
        print(f.read_text(encoding="utf-8"))
        return 0
    if a.action == "check":
        stale = build_all(out_dir, check=True)
        print("agents in sync" if not stale else f"out of sync: {stale}")
        return 0 if not stale else 1
    reg = SkillRegistry.discover() if a.installed_names else None
    changed = build_all(out_dir, registry=reg)
    print(f"wrote {changed}" if changed else "agents already up to date")
    return 0


def cmd_kb(a):
    project = _project()
    if a.action == "search":
        if a.scope != "global" and project is None and a.scope == "project":
            return _need_project() and 2
        hits = kb.search(a.query, project, scope=a.scope, limit=a.limit)
        _print([dataclasses.asdict(h) for h in hits], a.json,
               "\n".join(f"[{h.scope}] {h.title} — {h.path}\n    {h.snippet}" for h in hits) or "no hits")
        return 0
    if a.action == "add":
        meta = json.loads(Path(a.json_file).read_text(encoding="utf-8"))
        body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else meta.pop("body", "")
        if a.scope == "project":
            project = _need_project()
        print(kb.add_paper(meta, body, a.scope, project))
        return 0
    if a.action == "index":
        n = kb.index("global", None) + (kb.index("project", project) if project else 0)
        print(f"indexed {n} changed file(s)")
        return 0
    project = _need_project()
    if a.action == "queue":
        kb.queue_candidates(project)
        q = kb.list_queue(project)
        _print(q, a.json, "\n".join(f"{i['id']}  [{i['kind']}] {i['title']}  ({i['path']})" for i in q) or "queue empty")
        return 0
    if a.action == "promote":
        try:
            out = kb.promote(project, a.ids, approved=a.approved)
        except PermissionError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 3
        print("\n".join(str(p) for p in out) or "nothing promoted")
        return 0
    if a.action == "dismiss":
        print(f"dismissed {kb.dismiss(project, a.ids)}")
        return 0
    return 2


def cmd_budget(a):
    from .budget import Budget
    project = _need_project()
    s = Budget(project).summary()
    c = s["caps"]
    _print(s, a.json, f"project ${s['project_usd']:.2f} / ${c['max_usd_per_project']:.2f} "
                      f"(sessions ${s['session_usd']:.2f} over {s['sessions']}, GPU ${s['gpu_usd']:.2f}); "
                      f"session cap ${c['max_usd_per_session']:.2f}; GPU job cap ${c['max_gpu_usd_per_job']:.2f} at ${c['gpu_usd_per_hour']:.2f}/h")
    return 0


def cmd_job(a):
    from .jobs import run_job
    project = _need_project()
    cmd = a.cmd
    if not cmd:
        print("usage: ra job run [options] -- <command>", file=sys.stderr)
        return 2
    r = run_job(project, cmd, gpu_hours=a.gpu_hours, seed=a.seed, configs=a.config, data=a.data, metrics=Path(a.metrics) if a.metrics else None)
    print(json.dumps(r))
    return {"ok": 0, "blocked": 3}.get(r["status"], 1)


def cmd_loop(a):
    from .budget import Budget
    from .loops import LoopController
    project = _need_project()
    lc = LoopController(project)
    if a.action == "start":
        st = lc.start(a.goal, a.mode)
        _print(st, a.json, f"loop {a.mode} started" + (" (single pass)" if st["done"] else f": {' -> '.join(__import__('research_agent.loops', fromlist=['LOOPS']).LOOPS[a.mode])}"))
    elif a.action == "next":
        step = lc.next_step()
        _print(step, a.json, "no step: record the reviewer verdict and checkpoint" if step is None else
               f"iteration {step['iteration']}: dispatch {step['agent']}" + (f"; must fix: {step['must_fix']}" if step["must_fix"] else ""))
    elif a.action == "verdict":
        lc.record_verdict(a.verdict, a.must_fix or [])
        print(f"recorded {a.verdict.upper()}")
    elif a.action == "checkpoint":
        print(lc.checkpoint())
    elif a.action == "status":
        st = lc.status()
        if st and not a.json:
            stop = st["stop"]
            print(f"{st['mode']} loop, iteration {st['iteration']}, goal: {st['goal']}; stop: {stop['reason'] if stop['stop'] else 'no'}")
        else:
            _print(st, True)
        _ = Budget  # budget is consulted by the orchestrator through `ra budget show`
    return 0


def cmd_task(a):
    from .tasks import TaskStore
    ts = TaskStore(_need_project())
    if a.action == "create":
        t = ts.create(a.title, a.agent, a.type, plan_id=a.plan)
        _print(t, a.json, f"{t['id']}: {t['title']} -> {t['agent']} ({t['artifact_dir']})")
        return 0
    if a.action == "move":
        try:
            t = ts.transition(a.id, a.state, a.note or "")
        except (KeyError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{t['id']} -> {t['state']}")
        return 0
    items = ts.list(state=a.state)
    _print(items, a.json, "\n".join(f"{t['id']} [{t['state']}] {t['agent']}: {t['title']}" for t in items) or "no tasks")
    return 0


def cmd_gate(a):
    rep = gates.check(_need_project(), a.id, stage=a.stage)
    _print(dataclasses.asdict(rep), a.json,
           f"{a.id}: {'PASS' if rep.passed else 'FAIL'}\n" + "\n".join(f"  [{'ok' if ok else 'x '}] {n}: {msg}" for n, ok, msg in rep.checks))
    return 0 if rep.passed else 1


def cmd_approve(a):
    from .approvals import ApprovalStore
    store = ApprovalStore(_need_project())
    if a.action == "grant":
        store.grant(a.rule, a.target, ttl_hours=a.ttl)
        print(f"granted {a.rule} for {a.target!r} ({a.ttl:g} h)")
        return 0
    p = store.pending()
    _print(p, a.json, "\n".join(f"{x['rule']}: {x['target']} — {x['reason']}" for x in p) or "no pending approvals")
    return 0


def cmd_memory(a):
    from .memory import ProjectMemory
    m = ProjectMemory(_need_project())
    if a.action == "decide":
        m.decide(a.title, a.decision, a.rationale, a.alternatives or "")
    elif a.action == "progress":
        m.progress(a.note)
    else:
        print(m.summary(10000) or "no memory yet")
    return 0


def cmd_status(a):
    from .approvals import ApprovalStore
    from .budget import Budget
    from .loops import LoopController
    from .tasks import TaskStore
    project = _need_project()
    tasks = TaskStore(project).list()
    by_state: dict[str, int] = {}
    for t in tasks:
        by_state[t["state"]] = by_state.get(t["state"], 0) + 1
    data = {
        "project": str(project), "plugin_root": str(paths.plugin_root()),
        "plans": sorted(p.name for p in (paths.state_dir(project) / "plans").glob("*.md")),
        "tasks": by_state, "runs": len(provenance.list_runs(project)),
        "pending_approvals": len(ApprovalStore(project).pending()),
        "kb_queue": len(kb.list_queue(project)), "loop": LoopController(project).status() or None,
        "budget": Budget(project).summary(),
    }
    if a.json:
        _print(data, True)
    else:
        b = data["budget"]
        print(f"project: {data['project']}\nplugin: {data['plugin_root']}\nplans: {', '.join(data['plans']) or '-'}\n"
              f"tasks: {by_state or '-'}\nruns: {data['runs']}\npending approvals: {data['pending_approvals']}\n"
              f"knowledge queue: {data['kb_queue']}\nloop: {(data['loop'] or {}).get('mode', '-')}\n"
              f"budget: ${b['project_usd']:.2f} of ${b['caps']['max_usd_per_project']:.2f}")
    return 0


def cmd_device(a):
    from .device import detect
    _print(detect(), True)
    return 0


def cmd_run(a):
    from .sdk_runner import run
    return run(a.goal, a.loop, a.budget_usd, a.max_turns, _need_project(), dry_run=a.dry_run)


# ---- parser -----------------------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ra", description="Research-Agent command line")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    s = add("setup", cmd_setup, "set up this machine (~/.research-agent, ARIS pointer, reviewer MCP)")
    s.add_argument("--reviewer", choices=["claude", "codex"], default="claude")

    s = add("init", cmd_init, "make the current directory a Research-Agent project")
    s.add_argument("--protected", nargs="*", default=[], help="raw-data paths that must never be written")
    s.add_argument("--sensitive", nargs="*", default=[], help="PHI / identifiable data paths (reading needs approval)")
    s.add_argument("--irb", default="")
    s.add_argument("--budget-session", type=float)
    s.add_argument("--budget-project", type=float)

    s = add("doctor", cmd_doctor, "check the installation")
    s.add_argument("--skills", action="store_true")
    s.add_argument("--live", action="store_true")
    s.add_argument("--json", action="store_true")

    s = add("route", cmd_route, "which agent should do this task")
    s.add_argument("task")
    s.add_argument("--type")
    s.add_argument("--author")
    s.add_argument("--json", action="store_true")

    s = add("resolve", cmd_resolve, "which skills an agent should use for this task")
    s.add_argument("task")
    s.add_argument("--agent", required=True)
    s.add_argument("--type")
    s.add_argument("--max", type=int, default=4)
    s.add_argument("--json", action="store_true")

    s = add("agents", cmd_agents, "build or check agents/*.md from the registry")
    s.add_argument("action", choices=["build", "check", "show"])
    s.add_argument("name", nargs="?", default="orchestrator")
    s.add_argument("--installed-names", action="store_true", help="use invoke names discovered on this machine")

    s = add("kb", cmd_kb, "knowledge base")
    kbs = s.add_subparsers(dest="action", required=True)
    k = kbs.add_parser("search")
    k.add_argument("query")
    k.add_argument("--scope", choices=["all", "project", "global"], default="all")
    k.add_argument("--limit", type=int, default=10)
    k.add_argument("--json", action="store_true")
    k = kbs.add_parser("add")
    k.add_argument("--json-file", required=True)
    k.add_argument("--body-file")
    k.add_argument("--scope", choices=["project", "global"], default="project")
    kbs.add_parser("index")
    k = kbs.add_parser("queue")
    k.add_argument("--json", action="store_true")
    k = kbs.add_parser("promote")
    k.add_argument("--ids", nargs="+", required=True)
    k.add_argument("--approved", action="store_true", help="the user approved this promotion")
    k = kbs.add_parser("dismiss")
    k.add_argument("--ids", nargs="+", required=True)

    s = add("budget", cmd_budget, "budget status")
    s.add_argument("action", choices=["show"], nargs="?", default="show")
    s.add_argument("--json", action="store_true")

    s = add("job", cmd_job, "run an experiment with provenance and budget checks")
    s.add_argument("action", choices=["run"])
    s.add_argument("--gpu-hours", type=float, default=0.0)
    s.add_argument("--seed", type=int)
    s.add_argument("--config", action="append", default=[])
    s.add_argument("--data", action="append", default=[])
    s.add_argument("--metrics")

    s = add("loop", cmd_loop, "research / coding / full loops")
    ls = s.add_subparsers(dest="action", required=True)
    l = ls.add_parser("start")
    l.add_argument("--mode", required=True, choices=["research", "coding", "full", "none"])
    l.add_argument("goal")
    l.add_argument("--json", action="store_true")
    for name in ("next", "status"):
        l = ls.add_parser(name)
        l.add_argument("--json", action="store_true")
    l = ls.add_parser("verdict")
    l.add_argument("verdict", choices=["PASS", "PASS_WITH_FIXES", "FAIL", "pass", "pass_with_fixes", "fail"])
    l.add_argument("--must-fix", nargs="*")
    ls.add_parser("checkpoint")

    s = add("task", cmd_task, "task state")
    ts = s.add_subparsers(dest="action", required=True)
    t = ts.add_parser("create")
    t.add_argument("title")
    t.add_argument("--agent", required=True)
    t.add_argument("--type", required=True)
    t.add_argument("--plan")
    t.add_argument("--json", action="store_true")
    t = ts.add_parser("move")
    t.add_argument("id")
    t.add_argument("state")
    t.add_argument("--note")
    t = ts.add_parser("list")
    t.add_argument("--state")
    t.add_argument("--json", action="store_true")

    s = add("gate", cmd_gate, "quality gates for a task")
    s.add_argument("action", choices=["check"])
    s.add_argument("id")
    s.add_argument("--stage", choices=["pre-review", "final"], default="final")
    s.add_argument("--json", action="store_true")

    s = add("approve", cmd_approve, "list or grant approvals")
    s.add_argument("action", choices=["list", "grant"])
    s.add_argument("rule", nargs="?")
    s.add_argument("target", nargs="?", default="*")
    s.add_argument("--ttl", type=float, default=24.0)
    s.add_argument("--json", action="store_true")

    s = add("memory", cmd_memory, "project memory")
    ms = s.add_subparsers(dest="action", required=True)
    m = ms.add_parser("decide")
    m.add_argument("title")
    m.add_argument("--decision", required=True)
    m.add_argument("--rationale", required=True)
    m.add_argument("--alternatives")
    m = ms.add_parser("progress")
    m.add_argument("note")
    ms.add_parser("show")

    s = add("status", cmd_status, "project status")
    s.add_argument("--json", action="store_true")

    add("device", cmd_device, "detected compute device")

    s = add("run", cmd_run, "headless run through the Claude Agent SDK")
    s.add_argument("--goal", required=True)
    s.add_argument("--loop", choices=["research", "coding", "full", "none"], default="none")
    s.add_argument("--budget-usd", type=float, default=5.0)
    s.add_argument("--max-turns", type=int, default=200)
    s.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tail: list[str] = []
    if "--" in argv:  # everything after `--` is the command for `ra job run`
        i = argv.index("--")
        argv, tail = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    args.cmd = tail
    if getattr(args, "command", None) == "approve" and args.action == "grant" and not args.rule:
        print("usage: ra approve grant RULE [TARGET]", file=sys.stderr)
        return 2
    try:
        return int(args.fn(args) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)
