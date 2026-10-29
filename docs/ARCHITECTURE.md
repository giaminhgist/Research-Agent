# Architecture

```
                 ┌──────────── Orchestrator (plan · route · gates · approvals · loops · memory) ────────────┐
                 │   ra route  → which agent        ra resolve → which skills (+ deps, missing keys)       │
 research ── methodology ── coding ── experiment ── writing ──────────► reviewer (fresh context)
                 │                                                     PASS / PASS_WITH_FIXES / FAIL       │
                 └─ hooks: guard · budget · provenance nudge · session context · KB queue · cost ledger ──┘
                      runtime (src/research_agent): registries · resolver · guard · budget · kb · provenance · gates · loops
```

## Components

| Module | Responsibility |
|---|---|
| `agent_registry.py` | Loads and validates `registry/agents.toml`: exactly seven agents, known models and tools, every skill id in the catalog, 1–12 core skills, no skill both core and borrowable |
| `skill_registry.py` | Discovers installed skills: plugins from `installed_plugins.json`, `~/.claude/skills`, `<project>/.claude/skills`, and builtins from the catalog. Merges catalog metadata (tags, task types, required env/tools). Builds the dependency graph from ARIS's `tools/skill-groups.tsv` and the catalog. Reports availability. |
| `skill_resolver.py` | `resolve(task, agent)` returns the core preload, the scored borrowable skills (keyword and task-type match), their dependency closure, and what is missing and why |
| `agent_factory.py` | Renders `agents/*.md` (Claude Code subagent files) from the registry, `registry/prompts/*.md` and `config/protocol.md`. A test keeps them in sync. |
| `routing_policy.py` | `route(task)` returns the agent, task type, confidence and rationale from `registry/routing.toml`. Review always goes to the reviewer, never to the author. |
| `guard.py`, `shellparse.py`, `approvals.py` | allow/ask/deny for every tool call (see SAFETY.md), with time-limited grants |
| `budget.py` | Three-tier budget, session cost from the transcript, ledger |
| `hooks.py` | PreToolUse (guard and budget), PostToolUse (provenance nudge), SessionStart (memory, budget, PATH), SubagentStop (knowledge queue), Stop/SessionEnd (cost ledger) |
| `kb.py` | FTS5 knowledge base: global and per project, paper pages with BibTeX, a promotion queue, approval-gated promotion |
| `memory.py`, `tasks.py`, `trace.py` | Project memory (ADR-style decisions, progress, state), the task state machine, the audit trail |
| `provenance.py`, `jobs.py`, `device.py` | Run manifests, the budgeted job runner, cuda → mps → cpu detection |
| `evidence.py`, `gates.py`, `loops.py` | Claim lint, quality gates, Research/Coding/Full loops with stop conditions |
| `cli.py`, `setup.py`, `doctor.py`, `sdk_runner.py` | The `ra` CLI, machine/project setup, installation checks, the headless runner |

## Task lifecycle

```
planned → dispatched → artifact_ready → in_review → passed → done
              │               ▲              │
              ├→ needs_approval ┘            └→ failed → dispatched (with MUST_FIX)
```

## Per-project state (`<project>/.research-agent/`)

```
project.toml        config overrides (protected/sensitive paths, budget, autonomy)
plans/              orchestrator plans
tasks/tasks.json    task state + history
artifacts/<task>/   specialist outputs + handoff block
reviews/<task>.md   reviewer verdicts
runs/<run_id>/      manifest.json, log.txt, pip_freeze.txt
approvals/          pending.jsonl, granted.jsonl, pending.md (headless)
kb/                 papers/, notes/, library.bib, promotion-queue.jsonl, FTS index
memory/             decisions.md, progress.md, state.json, log.jsonl
checkpoints/        loop iteration summaries
loop.json           current loop state
budget.jsonl        cost ledger (sessions + GPU jobs)
trace.jsonl         audit trail
```

## Why registries instead of a static skill map

Skills move. Repos add, rename or remove them; Supervisor-Skills installs user-level, so its skills have bare names, while ARIS installs as a plugin, so its skills are `aris:`-prefixed. API keys and tools also differ per machine. The skill registry discovers what is actually installed. The resolver adds task-specific skills and their dependencies, and reports what cannot run and why. `ra doctor` checks that every agent's core skills are installed.

The preload list (`skills:` in the agent files) is a default, not a fence: any agent can load any installed skill with the Skill tool. A spike confirmed that Claude Code preloads plugin, bare user-level and builtin skill names for subagents, but not when an agent runs as the main thread (see SKILLS.md).
