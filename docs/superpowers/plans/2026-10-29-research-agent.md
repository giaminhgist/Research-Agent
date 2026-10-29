# Research-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user-level Claude Code plugin, plus a stdlib Python runtime (`ra` CLI and hooks). It provides 1 orchestrator and 6 specialist agents generated from a registry, and a skill resolver over the 4 upstream skill repos installed their own way. It enforces guardrails, a 3-tier budget, provenance, a global/project KB with an approval-gated promotion step, loop modes, and quality gates.

**Architecture:**
- `registry/*.toml` is the source of truth. `agent_factory` renders `agents/*.md` from it. At dispatch time the orchestrator calls `ra route` and `ra resolve` to choose an agent and its skills.
- Safety runs in Claude Code hooks, which call `research_agent.hooks`. That module calls guard, budget, approvals and kb. All logic lives in importable modules, so it can be tested without Claude.
- `install.py` installs each upstream repo the way that repo's README says. It never installs them through this plugin's marketplace.

**Tech Stack:** Python ≥ 3.11 standard library only (tomllib, sqlite3 FTS5, pathlib, subprocess, shlex). Tests use pytest. `claude-agent-sdk` is an optional extra for headless runs. CI runs on GitHub Actions (ubuntu-latest and windows-latest, Python 3.11 and 3.13).

**Spec:** `docs/superpowers/specs/2026-10-29-research-agent-design.md`

## Global Constraints
- Python ≥ 3.11. The runtime imports nothing outside stdlib. `claude_agent_sdk` is imported lazily in `sdk_runner.py` only.
- Paths:
  - Package: `src/research_agent/`.
  - Machine home: `~/.research-agent/`, overridable with env `RA_HOME`.
  - Per-project state: `<project>/.research-agent/`.
  - Claude home: `~/.claude`, overridable with env `CLAUDE_CONFIG_DIR`.
- Plugin name: `research-agent`. Its `.claude-plugin/marketplace.json` lists only `research-agent`, and `plugin.json` has no `dependencies`.
- Upstream install routes:
  - superpowers: `claude plugin install superpowers@claude-plugins-official --scope user`.
  - ARIS: `claude plugin marketplace add wanshuiyin/Auto-claude-code-research-in-sleep`, then `claude plugin install aris@aris --scope user`.
  - humanizer: `claude plugin marketplace add blader/humanizer`, then `claude plugin install humanizer@humanizer --scope user`.
  - Supervisor-Skills: `npx skills add HKUSTDial/Supervisor-Skills --global --agent claude-code`. Fallback when there is no npx (this machine has none): `git clone` to a temp dir and copy `skills/*` into `~/.claude/skills/`.
- Expected skill counts: superpowers 15, aris 87, supervisor-skills 12, humanizer 1.
- Default models are aliases: orchestrator, methodology, writing and reviewer use `opus`; research, coding and experiment use `sonnet`.
- Budget defaults:

  | Key | Default |
  |---|---|
  | `max_usd_per_session` | 10.0 |
  | `max_usd_per_project` | 100.0 |
  | `max_gpu_usd_per_job` | 5.0 |
  | `gpu_usd_per_hour` | 1.5 |
  | `warn_fraction` | 0.8 |
  | `max_loop_iterations` | 3 |
  | `max_consecutive_fails` | 2 |
  | `max_subagents_per_session` | 20 |
  | `max_parallel_subagents` | 3 |

- Autonomy levels: `supervised | semi | autonomous`. The default is `semi`. Autonomy never turns a deny into an allow.
- Evidence labels: `[SOURCED:key1,key2]`, `[INFERRED]`, `[HYPOTHESIS]`, `[RUN:run_id]`. Reviewer verdicts: `PASS | PASS_WITH_FIXES | FAIL`.
- Every file must work on Windows: use pathlib, no hard-coded `/`, no symlinks, and hooks run through Git Bash (`hooks/run.sh`).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Run tests with `.venv/bin/pytest -q`.

## Review Focus
1. **Windows-style or relative paths to protected data** (`data\raw\a.csv`, `./data/raw/../raw/a.csv`). The guard must still deny writes. Test in Task 5.
2. **Indirect shell writes** (`cd data/raw && rm a.csv`, `python -c "open('data/raw/a.csv','w')"`, `tee data/raw/x`). Expect deny for the cd/rm and tee forms, and at least ask for an inline interpreter that mentions a protected path. Test in Task 5.
3. **Missing or corrupt transcript when computing session cost.** This must not crash and must not block every dispatch. The result is cost unknown → `warn`, while the project ledger total is still enforced. Test in Task 6.
4. **Hooks fired in a directory that is not a Research-Agent project.** Exit 0, no output, no files created. Test in Task 7.
5. **Re-running `install.py`, or running it on a machine with partial installs or name collisions in `~/.claude/skills`.** Already-installed plugins are skipped, colliding skill dirs are skipped and reported, and nothing is overwritten without `--force`. Test in Task 12.

---

### Task 1: Scaffold, paths, config, CI

**Files:**
- Create: `pyproject.toml`, `.gitignore` (`.venv/`, `__pycache__/`, `*.egg-info`), `src/research_agent/__init__.py` (`__version__ = "0.1.0"`), `src/research_agent/paths.py`, `src/research_agent/config.py`, `config/default.toml`, `config/project.template.toml`, `tests/conftest.py`, `tests/test_paths_config.py`, `.github/workflows/ci.yml`
- `pyproject.toml`: setuptools, src layout, `[project.scripts] ra = "research_agent.cli:main"`, `[project.optional-dependencies] sdk = ["claude-agent-sdk"]`, `dev = ["pytest"]`, `[tool.pytest.ini_options] pythonpath = ["src"]`.

**Interfaces (Produces):**
- `paths.ra_home() -> Path`
- `paths.claude_home() -> Path`
- `paths.plugin_root() -> Path` (env `CLAUDE_PLUGIN_ROOT`, otherwise the repo root derived from `__file__`)
- `paths.find_project_root(start: Path) -> Path | None`: nearest ancestor containing `.research-agent/`. It never returns `Path.home()` or above.
- `paths.state_dir(project: Path) -> Path`
- `paths.is_within(p: Path, root: Path) -> bool`: resolves both, case-insensitive on Windows.
- `config.load(project: Path | None = None) -> dict`: deep-merges `config/default.toml`, then `ra_home()/config.toml`, then `<project>/.research-agent/project.toml`.
- `config.get(cfg: dict, dotted: str, default=None)`
- `conftest` fixtures:
  - `tmp_home`: sets `RA_HOME` and `CLAUDE_CONFIG_DIR` to tmp dirs.
  - `project`: a tmp dir with `.research-agent/project.toml` holding `[data] protected_paths=["data/raw"] sensitive_paths=["data/phi"]`.

`config/default.toml` sections:
- `[budget]` with all keys from Global Constraints
- `[pricing.opus|sonnet|haiku]` with `input`, `output`, `cache_write`, `cache_read` in USD per MTok. Copy the values from the `claude-api` skill's pricing reference (read it in this task).
- `[autonomy] level="semi"`
- `[data] protected_paths=[] sensitive_paths=[]`
- `[reviewer] backend="claude"`
- `[loop] default="none"`
- `[knowledge] search_limit=10`

- [ ] **Step 1: Write the failing tests:**
  - `test_find_project_root_walks_up`: nested `a/b/c` under `project` → returns `project`.
  - `test_find_project_root_none_outside`: tmp dir without a marker → `None`.
  - `test_config_layering`: project.toml sets `budget.max_usd_per_session=2.5` → `get(load(project),"budget.max_usd_per_session")==2.5`, and `get(..., "budget.max_usd_per_project")==100.0`.
  - `test_is_within`: `is_within(project/"x", project)` and `not is_within(project.parent, project)`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_paths_config.py -v`. Expect FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement** `paths.py`, `config.py` and the TOML files.
- [ ] **Step 4: Run** the tests. Expect PASS. Then `.venv/bin/pip install -e .` and `.venv/bin/ra --help` once the CLI exists (Task 11).
- [ ] **Step 5: Write `ci.yml`.** Matrix: `os: [ubuntu-latest, windows-latest]`, `python: ["3.11","3.13"]`, steps `pip install -e .[dev]` and `pytest -q`.
- [ ] **Step 6: Commit** `feat: scaffold, paths, layered config, CI`.

### Task 2: Spike — what `skills:` frontmatter accepts (throwaway)

No production code. The result is a written finding.
- [ ] **Step 1:** Create a scratch plugin in `/tmp/ra-spike/` (marketplace + one agent). Its frontmatter `skills:` should contain `superpowers:brainstorming` (plugin), `deep-research` (a user skill, after copying one Supervisor skill to `~/.claude/skills/` from the tutu cache copy), and `code-review` (builtin).
- [ ] **Step 2:** Run `claude plugin marketplace add /tmp/ra-spike` and install it. Then run `claude -p --agent spike:probe "List the skills preloaded in your context verbatim (names only)." --max-budget-usd 0.5`. Record which of the three appear.
- [ ] **Step 3:** Uninstall the spike and remove its marketplace. Write the finding to `docs/SKILLS.md` under "Preload compatibility": does `builtin_preload` work (true/false), and do bare user-skill names work? Task 4 reads `BUILTIN_PRELOAD` from this result.
- [ ] **Step 4: Commit** `docs: preload compatibility spike result`.

### Task 3: Skill registry (discovery, metadata, dependencies, availability)

**Files:**
- Create: `src/research_agent/frontmatter.py`, `src/research_agent/skill_registry.py`, `registry/skills_catalog.toml`, `tests/fixtures/claude_home/` (fake `plugins/installed_plugins.json`, plugin dirs `aris/skills/{research-lit,exa-search,paper-writing,paper-plan}/SKILL.md` and `aris/tools/skill-groups.tsv`, `superpowers/skills/brainstorming/SKILL.md`, `humanizer/SKILL.md`, user skills `skills/deep-research/SKILL.md`), `tests/test_skill_registry.py`

**Interfaces (Produces):**
- `frontmatter.parse(text: str) -> tuple[dict, str]`: handles `key: value`, quoted values, `>`/`|` block scalars and simple `- item` lists. It returns `({}, text)` when there is no frontmatter. Task 4 reuses it.
- `@dataclass Skill` with fields:
  - `id: str`: canonical, `<repo>:<name>`, where repo is one of `superpowers|aris|supervisor-skills|humanizer|builtin|user|project`
  - `name: str`
  - `source: str`
  - `invoke_as: str`: the name Claude Code accepts, either `aris:research-lit` or bare `deep-research`
  - `description: str`
  - `path: Path | None`
  - `installed: bool`
  - `tags: list[str]`
  - `task_types: list[str]`
  - `requires_env: list[str]`
  - `requires_tools: list[str]`
  - `depends_on: list[str]`
- `class SkillRegistry`:
  - `SkillRegistry.discover(claude_home: Path, project: Path | None = None, catalog_path: Path = <plugin_root>/registry/skills_catalog.toml) -> SkillRegistry`
  - `.get(id_or_name: str) -> Skill | None`: accepts a canonical id, `invoke_as`, or a bare name when unambiguous.
  - `.all() -> list[Skill]`
  - `.counts_by_source() -> dict[str, int]`
  - `.available(id: str, env: Mapping = os.environ) -> tuple[bool, list[str]]`: returns the missing items as `"not installed"`, `"env:EXA_API_KEY"` or `"tool:latexmk"`.
  - `.dependency_closure(ids: list[str]) -> list[str]`: dependency order, cycle-safe.
- `REPO_OF_PLUGIN = {"superpowers": "superpowers", "aris": "aris", "humanizer": "humanizer", "supervisor-skills": "supervisor-skills"}`. Discovered skills from other plugins get source = the plugin name.

**Discovery rules:**
- Read `installed_plugins.json` (v2). For each `name@marketplace` → `installPath`, scan `skills/*/SKILL.md` plus a root `SKILL.md`. Skip `skills/skills-codex*` and dirs with no SKILL.md.
- `~/.claude/skills/*/SKILL.md` gets source `user`. But if the catalog lists the name under `supervisor-skills`, the id is `supervisor-skills:<name>` and `invoke_as` is the bare name.
- `<project>/.claude/skills` gets source `project`.
- Catalog entries with `source="builtin"` are always `installed=True` with `invoke_as` = the name.
- ARIS `depends_on` comes from `tools/skill-groups.tsv` lines `skill\t<name>\t<group>\t<requires>\t<desc>`. Split `requires` on commas, map `-` to none, and prefix each with `aris:`. The catalog's own `depends_on` is merged in.

**Catalog content:**
- One `[skills."<id>"]` table for every skill mapped in spec §3 (core and borrow) and for the 13 builtins, with `tags`, `task_types` (from `literature, ideation, design, implement, debug, run, analyze, write, figures, review, plan, knowledge`), `requires_env` and `requires_tools`. Fill these from each SKILL.md and ARIS `.env.example`. Examples: `aris:exa-search` requires_env `["EXA_API_KEY"]`; `aris:paper-compile` requires_tools `["latexmk"]`; `aris:gemini-search` and `aris:paper-illustration` require `GEMINI_API_KEY`.
- A `[unmapped]` table, `ids = [...]`, listing the spec's unmapped-but-discoverable skills.

- [ ] **Step 1: Write the failing tests:**
  - `test_discovers_plugin_user_and_builtin`: `get("aris:research-lit").invoke_as == "aris:research-lit"`, `get("supervisor-skills:deep-research").invoke_as == "deep-research"`, `get("builtin:code-review").installed`.
  - `test_aris_dependencies_from_tsv`: the fixture tsv has `paper-writing` requiring `paper-plan` → `"aris:paper-plan" in dependency_closure(["aris:paper-writing"])`.
  - `test_availability_env`: `available("aris:exa-search", env={})` returns `(False, ["env:EXA_API_KEY"])`, and with `{"EXA_API_KEY": "x"}` returns `(True, [])`.
  - `test_not_installed`: a catalog id absent from the fixtures → `(False, ["not installed"])`.
  - `test_frontmatter_block_scalar`: `description: >\n  a\n  b` → `"a b"`.
  - `test_real_machine_counts` (marked `skipif` when `~/.claude/plugins/installed_plugins.json` is missing): counts by source are aris 87, superpowers 15, humanizer 1, and supervisor-skills 12 whether installed as plugin or user.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement** `frontmatter.py`, `skill_registry.py` and `skills_catalog.toml`.
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: skill registry with discovery, deps and availability`.

### Task 4: Agent registry, resolver, routing, factory → generated agents

**Files:**
- Create: `registry/agents.toml`, `registry/routing.toml`, `registry/prompts/{orchestrator,research,methodology,coding,experiment,writing,reviewer}.md`, `config/protocol.md`, `config/domain/{eye-tracking,medical-imaging,dementia-clinical,representation-learning,reporting-standards}.md`, `src/research_agent/{agent_registry,skill_resolver,routing_policy,agent_factory}.py`, `agents/*.md` (generated), `tests/test_agents.py`

**Interfaces:**
- Consumes `SkillRegistry`, `Skill` and `frontmatter.parse` from Task 3.
- `@dataclass AgentSpec` with fields: `name`, `role` (the "You are …" sentence), `description`, `model`, `color`, `tools: list[str]`, `core_skills: list[str]`, `borrow_skills: list[str]` (canonical ids), `responsibilities: list[str]`, `write_scope: list[str] | None` (the reviewer gets `[".research-agent/reviews"]`).
- `agent_registry.AGENT_NAMES = ("orchestrator","research","methodology","coding","experiment","writing","reviewer")`
- `agent_registry.KNOWN_TOOLS`: Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion, WebSearch, WebFetch, TodoWrite, NotebookEdit, and the prefix `mcp__`.
- `agent_registry.load_agents(path: Path | None = None) -> dict[str, AgentSpec]`
- `agent_registry.validate(agents, catalog_ids: set[str]) -> list[str]` (errors).
- `class RegistryError(Exception)`: raised by `load_agents` when `validate` returns errors. Checks:
  - exactly the 7 names
  - model in `{opus, sonnet, haiku, inherit}` or a string starting `claude-`
  - tools known
  - every skill id in the catalog
  - `1 <= len(core_skills) <= 12`
  - no skill in both core and borrow
- `@dataclass Resolution`: `agent: str`, `preload: list[str]` (invoke names), `borrowed: list[tuple[str, str]]` (invoke name, reason), `missing: list[tuple[str, str]]` (id, reason), `dependencies: list[str]`.
- `skill_resolver.resolve(task: str, agent: AgentSpec, registry: SkillRegistry, task_type: str | None = None, max_borrow: int = 4, env: Mapping = os.environ) -> Resolution`:
  - Candidates are `agent.borrow_skills` plus catalog skills whose `task_types` contain `task_type`.
  - Score: 2 × keyword hits (lower-cased word tokens of `task` ∩ tags ∪ name tokens split on `-`), +3 if task_type matches, +1 if in the agent's borrow list.
  - Keep candidates with score ≥ 2, sorted by score then id, capped at `max_borrow`.
  - Add `dependency_closure` of the chosen skills.
  - Anything unavailable goes to `missing` with its reason. Core skills always go to `preload` when installed; otherwise to `missing`.
- `@dataclass Route`: `agent`, `task_type`, `confidence: float`, `rationale: str`.
- `routing_policy.route(task: str, task_type: str | None = None, author_agent: str | None = None, rules_path: Path | None = None) -> Route`:
  - `routing.toml` holds `[[rule]] task_type, agent, keywords` in this order: review→reviewer, write→writing, run/analyze→experiment, implement/debug→coding, ideation/design→methodology, literature→research, plan→orchestrator.
  - Phrase matching uses word boundaries, case-insensitively. The highest hit count wins; ties go to the earlier rule. With no hits the route is `orchestrator`, `task_type="plan"`, confidence 0. Confidence = hits / (hits + 1).
  - Hard rule: if `task_type=="review"` or the review rule matched, the agent is `reviewer`, and the rationale includes `"fresh context"`. A route never returns `author_agent` for a review.
- `agent_factory.BUILTIN_PRELOAD: bool` (from the Task 2 spike).
- `agent_factory.render_agent(spec: AgentSpec, registry: SkillRegistry | None, protocol: str, body: str) -> str`:
  - Frontmatter keys in order: `name, description, tools` (comma-joined), `skills` (YAML list of invoke names), `model`, `color`.
  - Body sections:
    1. `You are …`
    2. `Responsibilities:` as bullets
    3. the prompt body from `registry/prompts/<name>.md`
    4. `## Borrowable skills`, plus any builtins when `BUILTIN_PRELOAD` is false, with a line saying to load them via the Skill tool and to run `ra resolve` for task-specific picks
    5. `## Shared protocol`, the verbatim `config/protocol.md`
  - With `registry=None`, invoke names come from the catalog `invoke_as` defaults.
- `agent_factory.build_all(out_dir: Path, registry: SkillRegistry | None = None, check: bool = False) -> list[str]`: writes the files, or with `check=True` returns the names of out-of-sync files.

**`agents.toml` content:** the spec §3 tables, verbatim (core and borrow per agent, models, tools).

**Prompt bodies (`registry/prompts/*.md`):**
- Each has a Method section, an Inputs/Outputs section with artifact path `.research-agent/artifacts/<task-id>/`, and a Handoff block.
- Orchestrator: the dispatch procedure (spec §6), loop handling via `ra loop`, the KB promotion question after research/methodology/reviewer sessions (AskUserQuestion multiSelect over `ra kb queue --json`), and approvals.
- Reviewer: works from a fresh context, never reads the author's reasoning, only the artifacts. It writes `.research-agent/reviews/<task-id>.md` with a `VERDICT:` line and a `MUST_FIX:` list.

**`config/protocol.md`:**
- the evidence labels
- the handoff block format:
  ````
  ```handoff
  task_id:
  status: done|blocked
  artifacts: [paths]
  claims_file:
  run_ids: []
  open_issues: []
  ```
  ````
- "never self-certify"
- the approval triggers
- reproducibility via `ra job run`
- project isolation

**Domain checklists:** subject-level splits for eye-tracking and imaging, leakage sources, class imbalance, site/scanner confounds, CLAIM, TRIPOD-AI, STARD, CONSORT-AI, and calibration and uncertainty reporting for dementia diagnosis.

- [ ] **Step 1: Write the failing tests:**
  - `test_registry_valid`: `load_agents()` passes, and every core and borrow id is in the catalog.
  - `test_validate_rejects_unknown_skill_and_tool`
  - `test_core_counts`: each agent has 8–12 core skills.
  - `test_unmapped_documented`: every id in `[unmapped]` is in neither core nor borrow, and `docs/SKILLS.md` mentions it. Write the SKILLS.md allocation table in this task.
  - `test_route_examples`, parametrized:
    - `"survey eye-tracking biomarkers for Alzheimer's"`→research
    - `"propose hypotheses and an ablation plan"`→methodology
    - `"implement a GRU baseline in PyTorch"`→coding
    - `"run 5-fold CV and compute bootstrap CIs"`→experiment
    - `"draft the Methods section in LaTeX"`→writing
    - `"review the training code for data leakage"`→reviewer
    - `"hello"`→orchestrator with confidence 0
  - `test_review_never_author`: `route("check this code", task_type="review", author_agent="coding").agent == "reviewer"`.
  - `test_resolver_borrows_and_flags_missing`, using the fixture registry:
    - research plus `"search exa for scanpath papers"` with env `{}` → `aris:exa-search` in `missing` with `env:EXA_API_KEY`
    - with the key set → in `borrowed`
    - writing plus `"make conference slides"` → `aris:paper-slides` borrowed
  - `test_agents_in_sync`: `build_all(Path("agents"), check=True) == []`.
  - `test_agent_frontmatter_shape`: parse each `agents/*.md`, with keys `name, description, tools, skills, model`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement** the four modules and write the registry, prompt, protocol and domain files.
- [ ] **Step 4: Generate the agents** with `.venv/bin/python -c "from research_agent.agent_factory import build_all; from pathlib import Path; build_all(Path('agents'))"`. Then run the tests and expect PASS.
- [ ] **Step 5: Commit** `feat: agent registry, skill resolver, routing policy, agent factory + generated agents`.

### Task 5: Guard and approvals

**Files:**
- Create: `src/research_agent/{approvals,guard,shellparse}.py`, `tests/test_guard.py`, `tests/test_approvals.py`

**Interfaces:**
- `approvals.ApprovalStore(project: Path)`:
  - `.request(rule: str, target: str, reason: str, headless: bool = False) -> dict`: appends to `approvals/pending.jsonl` and, when headless, also to `pending.md`. Returns `{id, rule, target, reason, ts}`.
  - `.grant(rule: str, target: str = "*", ttl_hours: float = 24, by: str = "user") -> dict`: writes to `granted.jsonl`.
  - `.is_approved(rule: str, target: str, now: float | None = None) -> bool`: an unexpired grant matches when its target equals the request target or is `*`.
  - `.pending() -> list[dict]`.
- `shellparse.segments(cmd: str) -> list[list[str]]`: splits on `; && || |` and newlines, then shlex-tokenizes each piece with posix mode, falling back to whitespace split when that fails.
- `shellparse.write_targets(cmd: str, cwd: Path) -> list[Path]`:
  - It tracks `cd X` within the command.
  - It collects redirect targets (`>`, `>>`, `2>`), `tee` args, `cp/mv/rsync/install` destination (last arg), `rm/rmdir/unlink/truncate/shred` args, `sed -i` files, `dd of=`, `touch`, and `mkdir`.
  - Paths are normalized with `\`→`/` and resolved against the cwd.
- `@dataclass Decision`: `action: Literal["allow","ask","deny"]`, `reason: str`, `rule: str`.
- `guard.evaluate(tool: str, tool_input: dict, cwd: Path, cfg: dict, project: Path | None, agent: str | None = None, approvals: ApprovalStore | None = None) -> Decision`

**Rules, evaluated in order (first deny wins, then ask, then allow):**

| Rule | Decision | Condition |
|---|---|---|
| `protected-write` | deny | Write, Edit, MultiEdit or NotebookEdit `file_path`, or any Bash `write_targets`, inside `data.protected_paths` (relative to the project) |
| `rm-outside` | deny | `rm -r`/`-rf`/`-fr` with a target outside the project, or a target of `/`, `~`, `$HOME` or `*` at the project root |
| `cross-project` | deny | any Read/Grep/Glob path or Bash token containing `.research-agent` that resolves outside this project's state dir. Exception: `ra_home()` |
| `reviewer-scope` | deny | `agent=="reviewer"` and Write/Edit outside `write_scope` |
| `phi-read` | ask | Read/Grep/Glob/Bash touching `data.sensitive_paths` |
| `publish` | ask | `git push`, `gh pr create\|merge`, `gh release`, `twine upload`, `npm publish`, arXiv/OpenReview submit, `overleaf-sync` push |
| `cloud-gpu` | ask | `vastai`, `modal run\|deploy`, `sbatch`, `qsub`, `runpodctl` |
| `network-send` | ask | `curl` with `-X POST\|-d\|--data\|-F\|-T`, `scp`, `rsync` to `host:` |
| `gpu-over-cap` | ask | `ra job run --gpu-hours H` with `H × gpu_usd_per_hour > max_gpu_usd_per_job` |
| `kb-promote` | ask | `ra kb promote` without `--approved` |
| `inline-protected` | ask | `python -c`/`-` or `perl -e` whose text mentions a protected path |

- In `supervised` mode, any `ra job run`, `pip install` or `conda install` also asks.
- Any "ask" whose `(rule, target)` is approved in the store becomes an allow.
- With `project is None`, only `rm-outside` (against the cwd) and `cross-project` apply.

- [ ] **Step 1: Write the failing tests.** `tests/test_guard.py` covers:
  - `test_write_tool_protected_denied`
  - `test_bash_redirect_protected_denied` (`echo x > data/raw/a.csv`)
  - `test_cd_then_rm_denied` (`cd data/raw && rm a.csv`, Review Focus 2)
  - `test_tee_denied`
  - `test_windows_and_dotdot_paths_denied`, which tests `data\\raw\\a.csv` via the Write tool and `./data/raw/../raw/a.csv` (Review Focus 1)
  - `test_inline_python_mentioning_protected_asks` (Review Focus 2)
  - `test_read_protected_allowed`
  - `test_phi_read_asks_until_granted` (ask, then `grant("phi-read")`, then allow)
  - `test_git_push_asks`
  - `test_curl_post_asks_get_allowed`
  - `test_cloud_gpu_asks`
  - `test_gpu_over_cap_asks`: `--gpu-hours 4` at 1.5/h is 6 > 5 → ask, while `--gpu-hours 2` → allow
  - `test_rm_rf_outside_denied`
  - `test_cross_project_read_denied`
  - `test_reviewer_write_scope`
  - `test_supervised_pip_install_asks_semi_allows`
  - `test_no_project_only_universal_rules`

  `tests/test_approvals.py` covers `test_grant_expiry` and `test_headless_request_writes_pending_md`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: guard policy and approval store`.

### Task 6: Budget (3 tiers)

**Files:**
- Create: `src/research_agent/budget.py`, `tests/test_budget.py`, `tests/fixtures/transcript.jsonl` (assistant messages with `message.id`, `message.model`, `message.usage`, with one message id repeated)

**Interfaces:**
- `budget.session_cost_from_transcript(path: Path, pricing: dict) -> float | None`:
  - Dedupe by `message.id`, keeping the last.
  - Model family = the first of `opus|sonnet|haiku` found in the model string, defaulting to `sonnet`.
  - cost = Σ tokens × rate / 1e6 over input, output, cache_creation_input_tokens (`cache_write` rate) and cache_read_input_tokens.
  - Returns `None` if the file is missing or unreadable. Unparseable lines are skipped.
- `class Budget(project: Path, cfg: dict)`:
  - Ledger at `.research-agent/budget.jsonl`, with lines `{"ts","kind":"session"|"gpu_job","id","usd","detail"}`.
  - `.record_session(session_id: str, usd: float) -> None`: append; the latest line per session id wins.
  - `.project_total(override: tuple[str, float] | None = None) -> float`: the sum of the latest session lines plus all gpu_job lines. `override` replaces one session's value.
  - `.check_dispatch(session_id: str, session_usd: float | None) -> tuple[str, str]` returns `("allow"|"warn"|"deny", message)`:
    - deny if `session_usd >= max_usd_per_session`
    - deny if `project_total(override) >= max_usd_per_project`
    - warn if either is ≥ `warn_fraction` of its cap
    - warn with "cost unknown" when `session_usd is None`, while still enforcing the project total
  - `.check_gpu_job(gpu_hours: float) -> tuple[bool, float, int]` returns `(ok, est_usd, timeout_s)`, where `timeout_s = int(min(gpu_hours, max_gpu_usd_per_job / gpu_usd_per_hour) * 3600)`.
  - `.record_gpu_job(job_id: str, gpu_hours: float) -> float`
  - `.summary() -> dict`

- [ ] **Step 1: Write the failing tests:**
  - `test_transcript_cost_dedupes` (compare against a hand-computed value from the fixture and the default pricing)
  - `test_missing_transcript_none` (Review Focus 3)
  - `test_session_cap_denies`
  - `test_project_cap_denies_across_sessions`: two prior sessions at 60 and 45, cap 100 → deny
  - `test_warn_at_80pct`
  - `test_unknown_cost_warns_but_project_cap_enforced`
  - `test_gpu_job_cap_and_timeout`: 2 h → ok, est 3.0, timeout 7200; 4 h → not ok
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: three-tier budget manager`.

### Task 7: Hooks

**Files:**
- Create: `hooks/hooks.json`, `hooks/run.sh`, `hooks/dispatch.py`, `src/research_agent/hooks.py`, `tests/test_hooks.py`

**Interfaces:**
- Consumes `guard.evaluate`, `Budget`, `ApprovalStore`, `kb.queue_candidates` (Task 8; until Task 8 lands, stub the import behind try/except), and `memory.ProjectMemory.summary` (Task 8).
- `hooks.handle(event: str, payload: dict, env: Mapping = os.environ) -> dict | None`: returns the JSON to print, or None for no output.
  - `PreToolUse`:
    - For tool `Agent`/`Task`, first run the budget check using `session_cost_from_transcript(payload["transcript_path"])`. Deny → `permissionDecision: "deny"`. Warn → allow with `additionalContext` carrying the warning.
    - Also count dispatches per session in `<state>/sessions/<session_id>.json`. Deny once the count reaches `max_subagents_per_session`. `max_parallel_subagents` cannot be observed from hooks, so it is advisory and stated in the orchestrator prompt. Test: `test_subagent_count_cap`.
    - Then run `guard.evaluate`, with the agent taken from `payload.get("agent_type")`. An ask or deny maps to `{"hookSpecificOutput": {"hookEventName":"PreToolUse","permissionDecision":..., "permissionDecisionReason": "[research-agent:<rule>] <reason>"}}`.
    - A plain allow returns None, so normal permissions apply.
  - `PostToolUse` (Bash): if the command looks like training or evaluation (`python .*(train|eval|fit|finetune)`) and did not go through `ra job run`, return `additionalContext` reminding the agent to rerun via `ra job run` for provenance.
  - `SessionStart`: `additionalContext` with the memory summary, the pending approvals count, the budget summary and the number of queued promotion candidates.
  - `SubagentStop`: if `agent_type` (when present) is in `{research, methodology, reviewer}` (namespaced `research-agent:` accepted), or is absent, call `kb.queue_candidates(project, since=<last scan marker>)`. If new candidates exist, return `{"systemMessage": "N knowledge items queued for global KB — orchestrator must ask the user (ra kb queue)"}`.
  - `Stop` and `SessionEnd`: `Budget.record_session(session_id, cost)`.
  - Outside a project (`find_project_root(cwd)` is None): the only behavior is the PreToolUse universal guard rules. Never write files.
- `hooks/dispatch.py <Event>`: reads stdin JSON, adds `src/` to `sys.path` relative to its own location, calls `handle`, and prints JSON. Any exception prints to stderr and exits 0 (fail-open for hook errors only, logged to `ra_home()/hook-errors.log`).
- `hooks/run.sh`: tries `$RA_PYTHON`, `~/.research-agent/venv/bin/python`, `python3`, `py -3`, then `python`, and runs `dispatch.py "$@"`. It exits 0 if no Python ≥ 3.11 is found.
- `hooks.json`: PreToolUse with matcher `Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob|Agent|Task`, PostToolUse `Bash`, SessionStart, SubagentStop, Stop and SessionEnd. Each command is `bash "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" <Event>`.

- [ ] **Step 1: Write the failing tests:**
  - `test_pretool_deny_json_shape`
  - `test_pretool_allow_returns_none`
  - `test_agent_dispatch_denied_over_session_cap` (fixture transcript plus a cap of 0.0001)
  - `test_outside_project_noop_creates_nothing` (Review Focus 4: run every event in a bare tmp dir and assert the dir tree is unchanged)
  - `test_dispatch_script_end_to_end`: subprocess `python hooks/dispatch.py PreToolUse` with JSON on stdin → exit 0 and parseable JSON
  - `test_stop_records_session`
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: Claude Code hooks for guard, budget, provenance nudge, memory and KB queue`.

### Task 8: Knowledge base, project memory, task state

**Files:**
- Create: `src/research_agent/{kb,memory,tasks}.py`, `tests/test_kb.py`, `tests/test_memory_tasks.py`

**Interfaces:**
- `@dataclass Hit`: `scope`, `path: Path`, `title`, `snippet`, `score: float`.
- `kb.search(query: str, project: Path | None, scope: str = "all", limit: int = 10) -> list[Hit]`.
  - Indexes:
    - global: `ra_home()/knowledge/{papers,notes}` → `knowledge/.index.sqlite`
    - project: `<state>/kb/` plus `<project>/research-wiki/` → `<state>/kb/.index.sqlite`
  - Re-indexing is incremental by mtime, using FTS5 with bm25 and `snippet()`. If FTS5 is unavailable, fall back to a LIKE search.
  - It never opens another project's index.
- `kb.add_paper(meta: dict, body: str, scope: str, project: Path | None) -> Path`: `meta` has `title, authors: list, year, venue, doi|arxiv, tags`. The slug is `<lastname-ascii-lower><year>_<first-significant-title-word>`. It writes Markdown with frontmatter and appends a BibTeX entry to the scope's `library.bib`.
- `kb.bib_keys(project: Path | None) -> set[str]`: global plus project bib keys and paper slugs.
- `kb.queue_candidates(project: Path, since: float | None = None, origin_agent: str | None = None) -> list[dict]`:
  - Scans `<state>/kb/papers/*.md`, `<state>/kb/notes/*.md` and `research-wiki/papers/*.md` modified after `since`.
  - Skips files whose slug already exists globally or is already queued.
  - Appends `{id (sha1 of path, first 8 chars), path, title, kind: paper|note, origin_agent, ts, status:"queued"}` to `<state>/kb/promotion-queue.jsonl` and returns the new entries.
  - Updates `<state>/kb/.last_scan`.
- `kb.list_queue(project, status="queued") -> list[dict]`
- `kb.promote(project: Path, ids: list[str], approved: bool) -> list[Path]`:
  - Raises `PermissionError` unless `approved`.
  - Copies to `ra_home()/knowledge/{papers|notes}/`, adding `promoted_from: <project dir name>` and `promoted_at: <iso date>` to the frontmatter.
  - Marks the entries `promoted` and appends to the trace.
- `kb.dismiss(project, ids) -> int`
- `trace.append(project, event: str, **data)`: lives in `src/research_agent/trace.py`, writes `<state>/trace.jsonl`, and is created in this task.
- `memory.ProjectMemory(project)`:
  - `.decide(title: str, decision: str, rationale: str, alternatives: str = "") -> None`: appends an ADR to `memory/decisions.md`.
  - `.progress(note: str) -> None`
  - `.state() -> dict`
  - `.update_state(**kv) -> dict`: `memory/state.json`.
  - `.summary(max_chars: int = 1500) -> str`: the last 5 decisions, the last 5 progress notes, and the state keys.
- `tasks.STATES = ("planned","dispatched","artifact_ready","in_review","passed","failed","needs_approval","done")`
- `tasks.ALLOWED`: planned→dispatched; dispatched→artifact_ready|failed|needs_approval; artifact_ready→in_review; in_review→passed|failed; failed→dispatched; needs_approval→dispatched|failed; passed→done.
- `tasks.TaskStore(project)`:
  - `.create(title, agent, task_type, artifact_dir: str | None = None, plan_id: str | None = None) -> dict`: id `T<NNN>`, artifact dir defaulting to `.research-agent/artifacts/<id>/`.
  - `.transition(task_id, new_state, note="") -> dict`: raises `ValueError` on an illegal transition and records the history.
  - `.get(task_id)`
  - `.list(state=None)`

- [ ] **Step 1: Write the failing tests:**
  - `test_add_and_search_project_and_global`
  - `test_scope_isolation`: two projects A and B, a paper in A, searching from B with scope `all` → no hit
  - `test_queue_and_promote_requires_approval`: `promote(..., approved=False)` raises; with `approved=True` the global file exists with `promoted_from`
  - `test_queue_skips_already_global`
  - `test_slug_ascii` (`"Nguyễn"`, 2024, "Scanpath transformers for MCI" → `nguyen2024_scanpath`)
  - `test_task_illegal_transition` (planned→passed raises)
  - `test_memory_summary_truncates`
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS, including Task 7's tests with the real imports.
- [ ] **Step 5: Commit** `feat: knowledge base with approval-gated promotion, project memory, task state`.

### Task 9: Provenance, device, job runner

**Files:**
- Create: `src/research_agent/{provenance,device,jobs}.py`, `tests/test_provenance_jobs.py`

**Interfaces:**
- `device.detect() -> dict`: returns `{"device": "cuda"|"mps"|"cpu", "name": str, "count": int}`. It tries `torch`, then `nvidia-smi -L`, then falls back to cpu. Never raises.
- `provenance.capture(project: Path, cmd: list[str], seed: int | None, config_paths: list[Path], data_paths: list[Path]) -> str`:
  - The run id is `R<yyyymmdd-HHMMSS>-<4 hex>`.
  - It writes `<state>/runs/<id>/manifest.json` containing:
    - `run_id`, `cmd`, `cwd`
    - `git`: `{sha, dirty, diff_sha256}`, or null when not a repo
    - `data`: `{path: sha256}`; directories hash the sorted relative paths and file hashes; files over 1 GB hash size and mtime only, flagged `fast_hash`
    - `config`, `seed`
    - `env`: `{python, platform, executable}` and `pip_freeze.txt` saved beside the manifest
    - `device`
    - `started_at`
- `provenance.finalize(project, run_id, exit_code: int, metrics_path: Path | None = None) -> dict`: adds `ended_at`, `exit_code`, and `metrics` (JSON content if given).
- `provenance.exists(project, run_id) -> bool`
- `provenance.list_runs(project) -> list[dict]`
- `jobs.run_job(project: Path, cmd: list[str], gpu_hours: float = 0.0, seed: int | None = None, configs=(), data=(), cfg: dict | None = None) -> dict`:
  1. Calls `Budget.check_gpu_job` when `gpu_hours > 0`. If the job is not ok, it returns `{"status": "blocked", ...}` without running.
  2. Captures provenance.
  3. Sets env `RA_RUN_ID`, `PYTHONHASHSEED=seed` and `RA_SEED=seed`.
  4. Runs the subprocess with `timeout=timeout_s` (none for CPU), tees stdout and stderr to `runs/<id>/log.txt`, and finalizes.
  5. Records the GPU cost by actual wall hours × rate, capped at the estimate.
  6. Returns `{"status": "ok"|"failed"|"timeout"|"blocked", "run_id", "exit_code"}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_capture_manifest_fields` (in a tmp git repo)
  - `test_job_runs_cpu_command` (`[sys.executable, "-c", "print(1)"]` → ok, the manifest exists, and `log.txt` contains `1`)
  - `test_job_blocked_over_gpu_cap`
  - `test_device_cpu_fallback` (monkeypatch torch import failure and `shutil.which` → cpu)
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: provenance manifests, device detection, budgeted job runner`.

### Task 10: Evidence lint, quality gates, loops

**Files:**
- Create: `src/research_agent/{evidence,gates,loops}.py`, `tests/test_evidence_gates_loops.py`

**Interfaces:**
- `@dataclass Issue`: `line: int`, `kind: str`, `msg: str`.
- `evidence.lint(text: str, known_keys: set[str], run_exists: Callable[[str], bool]) -> list[Issue]`:
  - Claim lines are bullet lines (`- ` or `* `) under a heading whose text contains Claims, Findings, Results, Conclusion(s) or Key points.
  - Each must carry ≥ 1 label from Global Constraints. If not, it gets kind `unlabelled`.
  - `[SOURCED:k]` keys must be in `known_keys`, otherwise kind `unknown-source`.
  - `[RUN:id]` must exist, otherwise kind `unknown-run`.
- `@dataclass GateReport`: `task_id`, `passed: bool`, `checks: list[tuple[str, bool, str]]`.
- `gates.check(project: Path, task_id: str, stage: str = "final") -> GateReport`. Checks, in order:
  1. `artifact_exists`: the task's artifact dir has ≥ 1 file.
  2. `handoff`: a ```` ```handoff ```` block parses (the `status` key is required) in any `.md` in the artifact dir.
  3. `evidence`: lint is clean on `claims_file` (or on all artifact `.md` files).
  4. `runs`: every handoff `run_ids` entry exists.
  5. `review` (stage `final` only): `.research-agent/reviews/<task_id>.md` has `VERDICT: PASS` or `PASS_WITH_FIXES`.

  `stage="pre-review"` skips check 5.
- `loops.LOOPS = {"research": ["research","methodology","reviewer"], "coding": ["coding","experiment","reviewer"], "full": ["research","methodology","coding","experiment","reviewer"], "none": []}`
- `loops.LoopController(project: Path, cfg: dict)`:
  - State lives in `<state>/loop.json`.
  - `.start(goal: str, mode: str) -> dict`: raises `ValueError` on an unknown mode. Mode `none` returns a state with `done=True`.
  - `.next_step() -> dict | None`: returns `{"iteration", "agent", "must_fix"}`. When the steps of an iteration are exhausted it returns None and waits for `record_verdict`.
  - `.record_verdict(verdict: str, must_fix: list[str]) -> None`: PASS sets `passed`; FAIL increments `consecutive_fails`; PASS_WITH_FIXES resets it and carries `must_fix` forward.
  - `.should_stop(session_usd: float | None = None, budget: Budget | None = None) -> tuple[bool, str]`, where reason ∈ `{"reviewer_pass","max_iterations","budget","consecutive_fails",""}`. It checks, in order: pass, consecutive_fails ≥ `max_consecutive_fails`, budget deny, iteration ≥ `max_loop_iterations`.
  - `.checkpoint() -> Path`: writes `<state>/checkpoints/iter-<n>.md` (goal, mode, verdict, must_fix, budget summary) and increments the iteration.
  - `.status() -> dict`

- [ ] **Step 1: Write the failing tests:**
  - `test_lint_flags_unlabelled_and_unknown`
  - `test_lint_ignores_non_claim_sections`
  - `test_gate_fails_without_handoff_then_passes_with_review`
  - `test_loop_stops_on_pass`
  - `test_loop_stops_after_two_fails`
  - `test_loop_max_iterations`: with PASS_WITH_FIXES every iteration, it stops at 3 with reason `max_iterations`
  - `test_loop_budget_stop`
  - `test_loop_full_order`
  - `test_unknown_mode_raises`
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: evidence lint, quality gates, loop controller`.

### Task 11: CLI, setup/init, doctor, commands, headless runner

**Files:**
- Create: `src/research_agent/{cli,setup,doctor,sdk_runner}.py`, `bin/ra`, `bin/ra.cmd`, `bin/ra-py`, `commands/{ra,ra-init,ra-status,ra-kb,ra-loop,ra-approve}.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `requirements-skills.txt` (the same list the upstream skills need: numpy, scipy, pandas, matplotlib, seaborn, Pillow, python-pptx, pypdf, requests, pyyaml), `tests/test_cli.py`

**Interfaces:**
- `cli.main(argv: list[str] | None = None) -> int`. Subcommands (argparse; JSON output with `--json` where noted):
  - `setup [--reviewer claude|codex]`
  - `init [--protected P ...] [--sensitive P ...] [--irb ID] [--budget-session X] [--budget-project Y]`
  - `doctor [--skills] [--live]`
  - `route "<task>" [--type T] [--author A] [--json]`
  - `resolve "<task>" --agent A [--type T] [--json]`
  - `agents build|check`
  - `kb search Q [--scope]`, `kb add --json-file F --scope`, `kb queue [--json]`, `kb promote --ids ... [--approved]`, `kb dismiss --ids ...`
  - `budget show`
  - `job run [--gpu-hours H] [--seed S] [--config F]... [--data P]... -- CMD...`
  - `loop start --mode M "<goal>"`, `loop next`, `loop verdict V [--must-fix ...]`, `loop status`, `loop checkpoint`
  - `task create|move|list`
  - `gate check T [--stage]`
  - `approve list|grant RULE [TARGET] [--ttl H]`
  - `memory decide|progress|show`
  - `status`
  - `device`
  - `run --goal G [--loop M] [--budget-usd X] [--max-turns N] [--dry-run]`
- `setup.setup_machine(reviewer: str = "claude", runner=subprocess.run) -> list[str]` (actions taken):
  - Creates `ra_home()/{config.toml, knowledge/papers, knowledge/notes, knowledge/library.bib}` when missing.
  - Writes `~/.aris/repo` = the ARIS installPath, only if the file is missing or stale.
  - Reviewer `claude`: runs `claude mcp add claude-review -s user -- <python> <aris>/mcp-servers/claude-review/server.py` when `claude mcp list` lacks `claude-review`.
  - Reviewer `codex`: prints the `/aris:setup` steps (codex login needs the user).
- `setup.init_project(path: Path, protected, sensitive, irb, budget_session, budget_project) -> Path`: creates the `.research-agent/{plans,tasks,artifacts,runs,reviews,approvals,kb/papers,kb/notes,memory,checkpoints}` tree and `project.toml` from the template, and adds `.research-agent/runs/*/pip_freeze.txt` to `.gitignore`. It is idempotent.
- `@dataclass Check`: `name`, `ok: bool`, `detail: str`, `level: "error"|"warn"`.
- `doctor.run(skills: bool = False, live: bool = False) -> list[Check]`:
  - Checks Python ≥ 3.11 and that `claude` is on PATH.
  - Checks that plugins `superpowers@claude-plugins-official`, `aris@aris`, `humanizer@humanizer` and `research-agent@research-agent` are present.
  - Errors if any `*@tutu` is present.
  - Skill counts match Global Constraints.
  - Every core preload of every agent is installed (via `SkillRegistry`).
  - Warns about borrowable skills that lack env keys or tools.
  - Checks for the reviewer MCP in `claude mcp list`. With `--live`, its status must be `Connected`.
  - Checks that the `agents/` files are in sync.
- `sdk_runner.build_options(goal, loop, budget_usd, max_turns, project) -> dict` (plain dict, so tests need no SDK):
  - `system_prompt` = orchestrator body plus the headless rules
  - `max_budget_usd = min(budget_usd, max_usd_per_session)`
  - `permission_mode="default"`
  - `cwd`
  - `plugins=[{"type":"local","path": plugin_root()}]`
- `sdk_runner.permission_callback(project, cfg) -> Callable`: maps guard `ask` → deny plus `ApprovalStore.request(headless=True)`, and `deny` → deny.
- `sdk_runner.run(...) -> int`: lazy-imports `claude_agent_sdk`, otherwise prints an install hint and returns 2. `--dry-run` prints `build_options` as JSON.
- Command files:
  - `commands/ra.md`: the frontmatter `description` and `argument-hint: "<goal> [--loop research|coding|full|none]"`. The body tells the main thread to act as `research-agent:orchestrator` (read `agents/orchestrator.md` via `${CLAUDE_PLUGIN_ROOT}`), parse `--loop`, and follow its procedure.
  - The other commands call the matching `ra` subcommands through the `bin/ra` wrapper (`"${CLAUDE_PLUGIN_ROOT}/bin/ra"`), then summarize.
  - `ra-approve` lists pending approvals and grants the one the user picks via AskUserQuestion.
- `bin/ra`: a bash wrapper running `PYTHONPATH=<root>/src python3 -m research_agent "$@"`, using the same Python discovery as `hooks/run.sh`. `bin/ra.cmd` does the same with `py -3`. Also add `src/research_agent/__main__.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_cli_route_json`
  - `test_cli_resolve_json`
  - `test_init_idempotent`
  - `test_kb_promote_without_approved_flag_exits_nonzero`
  - `test_loop_cli_roundtrip`
  - `test_job_run_cli` (cpu echo)
  - `test_run_dry_run_prints_options` (no SDK needed)
  - `test_permission_callback_headless_denies_and_records`
  - `test_doctor_flags_tutu` (a fake installed_plugins with `superpowers@tutu` gives an error check)
  - `test_marketplace_lists_only_self` (`marketplace.json` plugins == `["research-agent"]` and `"dependencies" not in plugin.json`)
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite with `.venv/bin/pytest -q`. Expect all PASS.
- [ ] **Step 5: Commit** `feat: ra CLI, setup/init, doctor, slash commands, headless SDK runner`.

### Task 12: Installer with tutu migration

**Files:**
- Create: `install.py`, `tests/test_install.py`

**Interfaces:**
- `install.py` is standalone and stdlib only. It does not import `research_agent` until step 5.
- `class Runner`: `.run(cmd: list[str], check=True) -> CompletedProcess`, and `.dry_run: bool` (prints instead of executing).
- `installed_plugin_ids(claude_home) -> set[str]` and `known_marketplaces(claude_home) -> set[str]`, read from JSON.
- `plan_steps(state: dict, opts) -> list[Step]`. `Step` is `(name: str, cmds: list[list[str]] | Callable)`. The `state` dict is `{plugins, marketplaces, user_skills: set[str], has_npx: bool}`. Steps:
  1. `preflight`
  2. `migrate-tutu`: only if any `*@tutu` or a `tutu` marketplace exists. Requires a confirmation prompt unless `--yes`, and is skipped with `--skip-migrate`. It runs `claude plugin uninstall <id> --scope user` for each, then `claude plugin marketplace remove tutu`.
  3. `superpowers`
  4. `aris` (marketplace add, then install)
  5. `humanizer`
  6. `supervisor-skills`: npx route if `has_npx`, otherwise a clone and copy. Skill dirs that already exist in `~/.claude/skills` are skipped and reported unless `--force`. The manifest goes to `ra_home()/installed/supervisor-skills.json` with the git sha and names.
  7. `research-agent`: `claude plugin marketplace add <this dir>`, then `claude plugin install research-agent@research-agent --scope user`.
  8. `home`: `setup_machine(reviewer)` and a venv at `ra_home()/venv` with `requirements-skills.txt`.
  9. `extras`: `--with-latex` (apt `texlive-latex-extra latexmk biber` on Debian/Ubuntu, with a hint for winget/MiKTeX on Windows), `--with-drawio` (prints a guided hint), `--extras pkg...` (pip into the venv).
  10. `doctor --skills`
- Any step whose target is already installed emits no commands. Steps whose commands fail print the failing command and continue; the process exits 1 at the end if any step failed.
- `main(argv) -> int`, with flags `--dry-run --yes --skip-migrate --force --reviewer {claude,codex} --with-latex --with-drawio --extras ...`.

- [ ] **Step 1: Write the failing tests** (fake state, no subprocess):
  - `test_fresh_machine_commands`: the exact command lists for steps 3–7. No command contains `@tutu`, and none installs any of the 4 repos from `research-agent`.
  - `test_tutu_migration_commands_when_present`
  - `test_migration_skipped_without_confirmation` (input "n" → no uninstall commands, and the install continues)
  - `test_idempotent_rerun_emits_nothing_for_installed` (Review Focus 5)
  - `test_supervisor_fallback_copy_skips_collisions`: a tmp `~/.claude/skills/deep-research` exists; a fake clone dir with 12 skills → 11 copied, 1 reported (Review Focus 5)
  - `test_dry_run_executes_nothing`
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS. Then run `python3 install.py --dry-run` on this machine and read the printed plan. Expect migrate-tutu to list 5 uninstalls and the 4 upstream installs.
- [ ] **Step 5: Commit** `feat: cross-platform installer with upstream-native installs and tutu migration`.

### Task 13: Real install, end-to-end check, docs

**Files:**
- Create: `README.md` (English, with a Vietnamese quickstart section), `docs/ARCHITECTURE.md`, `docs/SAFETY.md`
- Modify: `docs/SKILLS.md` (the final allocation and the doctor output snapshot)

- [ ] **Step 1:** Ask the user before the real install. It uninstalls the tutu plugins. Then run `python3 install.py` (interactive confirmation at migrate-tutu).
- [ ] **Step 2:** Verify:
  - `claude plugin list` shows the 4 upstream ids and `research-agent@research-agent`, with no `@tutu`.
  - `ls ~/.claude/skills` shows the 12 Supervisor skills.
  - `~/.claude/plugins/cache/` has no `research-agent/*` dir containing upstream skills.
- [ ] **Step 3:** Run `ra doctor --skills --live`. Expect all error-level checks ok.
- [ ] **Step 4:** In a scratch project, run `ra init`. Then:
  - `claude -p "/research-agent:ra survey eye-tracking biomarkers for MCI, 5 papers max --loop research" --max-budget-usd 3`. Expect a plan in `.research-agent/plans/`, artifacts, a reviewer verdict file, a non-empty promotion queue, and an updated `budget.jsonl`.
  - `ra job run --seed 0 -- python -c "print('ok')"`. Expect a manifest with `device.device == "cpu"`.
  - `ra run --goal test --dry-run`.
- [ ] **Step 5:** Write the docs: install for Ubuntu and Windows, commands, loops, budget tiers, approvals, KB promotion, the skill allocation table, and troubleshooting.
- [ ] **Step 6: Commit** `docs: README, architecture, safety, skills`. Then run superpowers:requesting-code-review for a whole-branch review.
