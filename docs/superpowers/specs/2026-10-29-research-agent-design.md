# Research-Agent — Implementation Plan

## Context
The user is an AI and biomedical engineering researcher working on eye tracking, medical imaging, dementia diagnosis, computer vision and representation learning. They want **Research-Agent**: a multi-agent research system for Claude Code, packaged as a user-level plugin that works on Ubuntu and Windows, with CPU fallback when no GPU is present. It has one Orchestrator and six specialist agents (Research, Methodology, Coding, Experiment, Writing, Reviewer). The design principles are evidence-first, reproducibility-by-default, project isolation, human-in-the-loop, quality gates and cost-awareness.

This machine already has a predecessor, `/root/Tutu-Agent` (v0.2.0). Its weak points are what drive this rewrite:
- (a) It vendors the 4 skill repos through its own `tutu` marketplace, so they sit in `~/.claude/plugins/cache/tutu/...`. The user explicitly forbids this.
- (b) Skill mapping is a static hand-maintained table. There is no registry or resolver.
- (c) The budget has only a session cap. There is no per-project USD cap and no per-job GPU USD cap.
- (d) There are no loop modes.
- (e) There is no flow for promoting knowledge to the global KB.

**Decisions made with the user:**
- Rewrite from scratch in `/root/Research-Agent` (empty). Tutu is a reference only; no code is copied.
- The installer detects the old `*@tutu` plugins and the `tutu` marketplace, asks for confirmation, removes them, and reinstalls the 4 repos the upstream way.
- The default reviewer is a fresh-context Claude MCP (`claude-review`). `--reviewer codex` is optional and follows ARIS `/aris:setup`.
- Loop stop rule: Reviewer PASS, or `max_iterations` (3), or budget exhausted, or 2 consecutive FAILs. A checkpoint is written after every iteration.

Process note (superpowers): first commit this plan as `docs/superpowers/specs/2026-10-29-research-agent-design.md`. Then use superpowers:writing-plans for the task-level plan, and execute with TDD (superpowers:test-driven-development).

---

## 1. Upstream skill installation (never inside Research-Agent's cache)
Each repo is installed the way its own README says, at user scope:

| Repo | Official route used by `install.py` | Resulting skill ids |
|---|---|---|
| obra/superpowers | `claude plugin install superpowers@claude-plugins-official --scope user` | `superpowers:*` (15) |
| wanshuiyin/auto-claude-code-research-in-sleep | `claude plugin marketplace add wanshuiyin/Auto-claude-code-research-in-sleep` → `claude plugin install aris@aris --scope user` → steps equivalent to `/aris:setup`: write `~/.aris/repo`, register reviewer MCP (claude-review by default, codex if `--reviewer codex`) | `aris:*` (87) |
| blader/humanizer | `claude plugin marketplace add blader/humanizer` → `claude plugin install humanizer@humanizer` (fallback: `npx skills add blader/humanizer --global --agent claude-code`) | `humanizer:humanizer` |
| HKUSTDial/Supervisor-Skills | No manifest; the README says "install with Skills". Use `npx skills add HKUSTDial/Supervisor-Skills --global --agent claude-code`. Fallback: `git clone` to a temp dir and copy `skills/*` into `~/.claude/skills/` (Windows: copy, not symlink) | bare names: `deep-research`, `paper-writer`, … (12) |

- Research-Agent's own `.claude-plugin/marketplace.json` lists **only** `research-agent`, and `plugin.json` has **no** `dependencies`.
- `install.py` flow:
  1. preflight (python ≥ 3.11, `claude`, git, optional node/npx)
  2. migrate tutu (confirm → `claude plugin uninstall <p>@tutu`, `claude plugin marketplace remove tutu`)
  3. install the 4 repos
  4. add this checkout as marketplace `research-agent` and install `research-agent@research-agent`
  5. create `~/.research-agent/` (config, global KB, venv with `requirements-skills.txt`)
  6. optional `--with-latex`, `--with-drawio`, `--extras`
  7. `ra doctor`
- Every step is idempotent and has a `--dry-run`. On Windows it runs as `py -3 install.py`.
- **Builtin Claude Code skills** are in the catalog as source `builtin`: `code-review`, `security-review`, `simplify`, `dataviz`, `claude-api`, `init`, `run`, `loop`, `update-config`, `fewer-permission-prompts`, `workflow-authoring`, `plugin-authoring`, `keybindings-help`. Whether `skills:` frontmatter can preload builtin skills must be verified by an early spike. If it cannot, the factory moves them from `preload` to a "use via Skill tool" line in the prompt body.

## 2. Repo layout (`/root/Research-Agent`)
```
.claude-plugin/{plugin.json, marketplace.json}
install.py                      # cross-platform installer (stdlib only)
bin/{ra, ra.cmd, ra-py}         # CLI wrappers (bash + Windows cmd)
registry/
  agents.toml                   # SOURCE OF TRUTH: per-agent model, tools, description, core/borrow skills, responsibilities
  skills_catalog.toml           # curated metadata per skill id: tags, task_types, requires_env, requires_tools, depends_on
  routing.toml                  # task_type -> agent rules + keyword patterns
agents/*.md                     # GENERATED by agent_factory (committed; test asserts in sync)
commands/{ra.md, ra-init.md, ra-status.md, ra-kb.md, ra-loop.md, ra-approve.md}
hooks/{hooks.json, run.sh, run.cmd, *.py}
config/{default.toml, project.template.toml, protocol.md, domain/*.md}
src/research_agent/
  paths.py config.py            # ~/.research-agent home, .research-agent/ project root, layered TOML config
  agent_registry.py             # load+validate agents.toml (schema, known tools, models, skill ids exist in catalog)
  skill_registry.py             # discover installed skills (installed_plugins.json, ~/.claude/skills, <project>/.claude/skills, builtin list); parse SKILL.md frontmatter; merge catalog metadata; dependency graph (ARIS tools/skill-groups.tsv + catalog depends_on); availability (env keys/tools present)
  skill_resolver.py             # resolve(task, agent) -> core preload ∪ scored borrowed skills (tags/keywords/task_type) ∪ dependency closure, filtered by availability, capped; returns reasons
  agent_factory.py              # render agents/*.md from registry + resolver (canonical id -> actual invocation name, e.g. supervisor "deep-research")
  routing_policy.py             # route(task) -> agent (+ confidence, rationale); hard rules: review => reviewer (fresh ctx), never self-review
  tasks.py                      # task state machine: planned→dispatched→artifact_ready→in_review→passed|failed|needs_approval→done
  memory.py                     # project memory: decisions.md, progress.md, state.json (append-only log)
  kb.py                         # SQLite FTS5 (bm25) global (~/.research-agent/knowledge) + project (.research-agent/kb); add/search/promote
  budget.py                     # 3-tier ledger + checks (see §4)
  guard.py                      # allow/ask/deny policy for tool calls (see §4)
  approvals.py                  # pending/approved records; interactive vs headless
  provenance.py                 # run manifests: git sha+dirty diff hash, data hashes/DVC, config, seeds, env, pip freeze, device
  loops.py                      # loop modes + stop conditions + checkpoints
  gates.py                      # quality gates: artifact exists, handoff block, evidence labels, reviewer verdict, run_ids resolvable
  evidence.py                   # lint claims: [SOURCED:key] / [INFERRED] / [HYPOTHESIS]; cite keys resolve in KB/bib
  device.py                     # cuda→mps→cpu detection
  doctor.py setup.py cli.py     # `ra` CLI: setup, init, doctor, route, resolve, agents build, kb, budget, loop, task, gate, approve, status, run
  sdk_runner.py                 # headless loop via claude-agent-sdk (optional dep)
tests/                          # pytest per module; CI matrix ubuntu+windows
docs/{ARCHITECTURE.md, SKILLS.md, SAFETY.md}, README.md
```
- Runtime is stdlib only (tomllib, sqlite3, pathlib, subprocess). `claude-agent-sdk` is an optional extra.
- Per-project state lives in `<project>/.research-agent/`: plans, tasks, artifacts, runs, reviews, approvals, kb, memory, budget.jsonl, trace.jsonl.

## 3. Agents and skill allocation (preload ≈ 10 core; borrow via resolver)
Models default to the aliases `opus` and `sonnet` and can be overridden in config. The format follows the user's example (`name / description / tools / skills` frontmatter, then "You are …" and "Responsibilities:").

| Agent | Core preload |
|---|---|
| **orchestrator** (opus) | superpowers: brainstorming, writing-plans, dispatching-parallel-agents, subagent-driven-development, executing-plans, verification-before-completion · aris: research-pipeline, research-wiki, render-html · vibe-research-workflow |
| **research** (sonnet) | deep-research · aris: research-lit, arxiv, semantic-scholar, openalex, alphaxiv, deepxiv, research-wiki, wiki-enrich, citation-audit |
| **methodology** (opus) | aris: idea-discovery, idea-creator, novelty-check, research-refine, research-refine-pipeline, experiment-plan, ablation-planner, formula-derivation · idea-evaluator · superpowers: brainstorming |
| **coding** (sonnet) | superpowers: test-driven-development, systematic-debugging, using-git-worktrees, requesting-code-review, receiving-code-review, verification-before-completion · aris: research-implement-feature, experiment-bridge, web-debug-search · builtin simplify |
| **experiment** (sonnet) | aris: run-experiment, experiment-queue, monitor-experiment, training-check, analyze-results, result-to-claim, experiment-audit, system-profile · builtin dataviz · superpowers: verification-before-completion |
| **writing** (opus) | aris: paper-writing, paper-plan, paper-write, paper-figure, paper-compile, grant-proposal, rebuttal · paper-writer, intro-drafter, paper-polish · humanizer:humanizer |
| **reviewer** (opus) | aris: research-review, experiment-audit, paper-claim-audit, citation-audit, citation-crosscheck, kill-argument, integrity-forensics, result-to-claim · pre-submission-reviewer · builtin code-review |

Skills each agent commonly borrows through the resolver:

| Agent | Borrowable |
|---|---|
| orchestrator | loop, research-refine-pipeline, finishing-a-development-branch |
| research | exa-search, gemini-search, keenable-search, firecrawl-search, novelty-check, comm-lit-review |
| methodology | research-lit, research-review, proof-writer, proof-checker, idea-discovery-robot, lean-formalize |
| coding | code-review, security-review, finishing-a-development-branch, system-profile, claude-api |
| experiment | vast-gpu, serverless-modal, qzcli, dse-loop, paper-figure, ablation-planner |
| writing | tech-paper-template, benchmark-paper-template, rebuttal-guidance, figure-designer, drawio-reconstruction, figure-spec, mermaid-diagram, paper-illustration, paper-slides, paper-talk, paper-poster-html, overleaf-sync, auto-paper-improvement-loop, resubmit-pipeline, writing-systems-papers |
| reviewer | auto-review-loop, security-review, rebuttal-guidance, proof-checker, novelty-check |

- **Unmapped but discoverable:** patent ×9, meta-optimize/meta-apply, feishu-notify, interview-cheatsheet, pixel-art, deprecated paper-poster, auto-review-loop-llm/minimax. The list is documented in `docs/SKILLS.md` and asserted by a test.
- **Tools:**
  - Every agent gets Read/Grep/Glob/Bash/Skill.
  - Write/Edit: everyone except the reviewer. The reviewer may Write, but only into `.research-agent/reviews/`, enforced by the guard.
  - The orchestrator adds Agent and AskUserQuestion.
  - research, methodology and writing add WebSearch and WebFetch.
  - The reviewer adds the `mcp__claude-review__*` tools.
  - research and reviewer may spawn read-only subagents.
- **Agent bodies** contain the role, responsibilities, a method, and shared rules from `config/protocol.md`: evidence labels, the handoff block, artifact paths, approval triggers, "never self-certify". The dementia, eye-tracking and medical-imaging checklists are copied from `config/domain/` and written fresh: subject-level splits, leakage, CLAIM/TRIPOD-AI/STARD.

## 4. Safety: guard, approvals, budget
**guard.py**, used by the PreToolUse hook and the SDK permission callback:
- **deny** writes to `protected_paths` (raw data), including shell writes via redirects, mv/cp/rm targets, `sed -i`.
- **deny** `rm -rf` outside the project.
- **deny** any read of another project's `.research-agent/` (isolation).
- **ask** before:
  - reading `sensitive_paths` (PHI)
  - git push, PR, release
  - arXiv/OpenReview/Overleaf submits, package publish
  - cloud GPU (vastai, modal, sbatch/qsub)
  - network POST, scp
  - experiment launches whose estimated GPU cost exceeds the job cap
  - `kb promote`
- An approval is a record in `.research-agent/approvals/` (scope, expiry). Interactive sessions use AskUserQuestion. Headless runs deny the action and append it to `pending.md`.

**budget.py**, with a ledger in `.research-agent/budget.jsonl`:

| Cap | Enforcement |
|---|---|
| `max_usd_per_session` | Headless: SDK `max_budget_usd` plus a running check. Interactive: a PreToolUse hook on Agent/Task estimates session cost from the transcript `usage` with the price table in config, then warns at 80% and denies new subagent dispatch at 100%. |
| `max_usd_per_project` | Sum of ledger session records, written by Stop/SessionEnd hooks. When the cap is reached, new dispatches are blocked until the user raises it. |
| `max_gpu_usd_per_job` | Jobs are launched via `ra job run --gpu-hours H` (rate from config, `gpu_usd_per_hour`). The estimate is checked before launch and the job gets a wall-clock timeout of `cap / rate`. CPU jobs cost 0. Direct cloud launches always ask. |

- Further caps: `max_loop_iterations`, `max_subagents_per_session`, `max_parallel_subagents`.
- `autonomy` = `supervised` | `semi` (default) | `autonomous`. The level changes which actions require "ask" approval; it never changes what is denied.

## 5. Knowledge and memory
- **Global KB:** `~/.research-agent/knowledge/` holds `papers/<slug>.md`, `notes/`, `library.bib` and an FTS5 index.
- **Project KB:** `.research-agent/kb/` plus the ARIS `research-wiki/`, with its own index.
- **Search** scopes are project, global and all. A search never reads another project.
- **Promotion flow:** a SubagentStop hook fires for research, methodology and reviewer. It extracts new paper and knowledge candidates from the session's artifacts into `.research-agent/kb/promotion-queue.jsonl`. The orchestrator must then ask the user, with an AskUserQuestion multi-select, which candidates to promote. `ra kb promote --ids ...` copies them with provenance (source project and date) and logs to the trace. Nothing is promoted without approval.
- **Project memory** (`memory.py`): `decisions.md` (ADR-style), `progress.md`, `state.json` (current plan, task states, loop iteration). The SessionStart hook injects a short summary of it.

## 6. Orchestration, loops, gates
- **`/research-agent:ra <goal> [--loop research|coding|full|none]`** (default `none`):
  1. The orchestrator writes `plans/<id>.md`.
  2. For each task it calls `ra route` and `ra resolve` to get an agent and skill list with rationale.
  3. It dispatches with an explicit artifact path.
  4. When the agent finishes, it runs `ra gate check` on the result.
  5. It dispatches the Reviewer in a fresh context.
  6. It updates task state and memory.
- **Loops** (`loops.py`):

| Loop | Iteration |
|---|---|
| Research | research → methodology → reviewer |
| Coding | coding → experiment (smoke/CPU) → reviewer(code) |
| Full | research → methodology → coding → experiment → reviewer |
| None | single pass |

  A loop stops on Reviewer PASS, `max_iterations`, a budget cap, or 2 consecutive FAILs. Each iteration writes `checkpoints/<iter>.md`, and the Reviewer's must-fix list feeds the next iteration.
- **Gates:** artifact present, handoff block parsed, evidence lint clean (every claim labelled; `[SOURCED]` keys resolvable), run_ids have manifests, Reviewer verdict ∈ {PASS, PASS_WITH_FIXES}. The model's own "done" never counts.
- **Headless:** `ra run --goal ... --loop full --budget-usd N` via claude-agent-sdk.

## 7. Implementation order (TDD, small commits)
1. Commit the design doc, scaffold, `paths`/`config`, pytest+CI (ubuntu+windows).
2. Spike: confirm that plugin agent `skills:` accepts plugin-namespaced, user-level (bare) and builtin skill names. Confirm the npx `skills` route for Supervisor-Skills.
3. `skill_registry` (discovery against the real installs on this machine and fixtures) → `agent_registry` → `skill_resolver` → `routing_policy` → `agent_factory`. Generate `agents/*.md`, plus `registry/*.toml` with the allocation in §3.
4. `guard` + `approvals` + `budget` (3-tier) + hooks (PreToolUse, PostToolUse provenance, SessionStart, SubagentStop promotion, Stop/SessionEnd ledger).
5. `kb` + `memory` + `tasks` + `provenance` + `evidence` + `gates` + `loops`.
6. Commands, protocol, domain checklists, `cli`, `doctor`, `sdk_runner`.
7. `install.py` with tutu migration and upstream installs. Then run it for real on this machine, with user confirmation at the tutu-removal prompt.
8. Docs (README in English with Vietnamese quickstart, SKILLS.md, SAFETY.md).

## 8. Verification
- `pytest -q` covers:
  - guard rules
  - budget caps at all 3 tiers
  - resolver outputs for representative tasks
  - routing table
  - factory output in sync with `agents/*.md`
  - every mapped skill exists in the catalog
  - KB isolation and promotion requiring approval
  - loop stop conditions
  - gate failures
- `python install.py --dry-run`, then a real install. Check that `claude plugin list` shows superpowers@claude-plugins-official, aris@aris, humanizer@humanizer and research-agent@research-agent, that there is no `*@tutu`, and that `~/.claude/skills/` holds the 12 Supervisor skills.
- `ra doctor --skills --live`: skill counts (15/87/12/1), every preloaded skill resolvable, reviewer MCP round-trip.
- End to end in a scratch project: `/research-agent:ra-init`, then `/research-agent:ra survey eye-tracking biomarkers for MCI --loop research` with a small budget. Confirm that the plan, artifacts, reviewer verdict and promotion prompt appear and the budget ledger updates. Then do a CPU pilot with `--loop coding` and check the run manifest (seed, git sha, env, device=cpu).
- A headless dry run: `ra run --goal ... --dry-run`.
