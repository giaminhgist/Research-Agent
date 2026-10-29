# Research-Agent

Research-Agent is a multi-agent research system for [Claude Code](https://code.claude.com/docs). You give it a goal. It plans the work, finds evidence, implements, runs experiments, evaluates, keeps an audit trail, and returns reproducible artifacts.

- Install it once per machine, at user level. It then works in any project you open with Claude Code.
- It runs on Ubuntu, macOS and Windows.
- A GPU is optional. Without one, work runs on the CPU.

It was built for AI research in eye tracking, medical imaging, dementia diagnosis, computer vision and representation learning. Nothing in it is specific to those fields, except the domain checklists in `config/domain/`.

> Research-Agent ships **no skills of its own**. Its agents use four skill libraries, each installed **the way its own README says**, outside Research-Agent's plugin cache:
> - [superpowers](https://github.com/obra/superpowers)
> - [ARIS](https://github.com/wanshuiyin/auto-claude-code-research-in-sleep)
> - [Supervisor-Skills](https://github.com/HKUSTDial/Supervisor-Skills)
> - [humanizer](https://github.com/blader/humanizer)
>
> They also use the skills that come with Claude Code (`code-review`, `security-review`, `simplify`, `dataviz`, …).

## Agents

| Agent | Model | Role |
|---|---|---|
| **orchestrator** | Opus | Understands the goal, writes the task plan, routes tasks, checks artifacts, asks for approval, keeps task state and project memory, runs loops |
| **research** | Sonnet | Literature and knowledge: paper search, systematic reviews, evidence synthesis, SOTA comparison, research gaps, citation checks |
| **methodology** | Opus | Ideas and experiment design: hypotheses, methodology, feature engineering, statistical plan, cross-validation, ablations |
| **coding** | Sonnet | Research software engineer: Python/PyTorch, algorithms, ML pipelines, refactoring, debugging, unit tests, optimization |
| **experiment** | Sonnet | Execution and analysis: runs, GPU jobs, training monitoring, statistics, error analysis, reproducibility |
| **writing** | Opus | Scientific communication: manuscripts, proposals, rebuttals, Methods/Results/Discussion, figures, LaTeX, bibliography |
| **reviewer** | Opus | Independent critic: methodology, code, data leakage, statistics, reproducibility, manuscripts, validity of conclusions |

Each agent preloads about 10 core skills and can borrow others for a task. [docs/SKILLS.md](docs/SKILLS.md) has the full allocation.

Agents are generated from a registry rather than written by hand:

| File | Role |
|---|---|
| `registry/agents.toml` | Agent registry |
| `registry/skills_catalog.toml` | Skill metadata |
| `registry/routing.toml` | Routing rules |
| `src/research_agent/agent_factory.py` | Renders the registry into `agents/*.md` |

At dispatch time, the orchestrator calls `ra route` (task → agent) and `ra resolve` (task → skills, with missing API keys or tools reported).

## Install (once per machine)

You need [Claude Code](https://code.claude.com/docs), Python ≥ 3.11 and git. Node.js (`npx`) is recommended. Without it, Supervisor-Skills is installed by a git clone and copy instead. On Windows, Claude Code uses Git Bash.

```bash
git clone https://github.com/giaminhgist/Research-Agent.git ~/Research-Agent
cd ~/Research-Agent
python3 install.py                 # Windows: py -3 install.py
python3 install.py --dry-run       # print the plan, change nothing
```

`install.py` runs these steps:
1. Preflight: Python, `claude`, `git` and `npx`.
2. If an old **Tutu** install exists, it asks first, then uninstalls its `*@tutu` plugins and the `tutu` marketplace. Tutu bundled the skill repos inside its own cache.
3. Installs the four skill repos at user scope, the upstream way:
   - `claude plugin install superpowers@claude-plugins-official`
   - `claude plugin marketplace add wanshuiyin/Auto-claude-code-research-in-sleep`, then `claude plugin install aris@aris`
   - `claude plugin marketplace add blader/humanizer`, then `claude plugin install humanizer@humanizer`
   - `npx skills add HKUSTDial/Supervisor-Skills --global --agent claude-code`, which puts the 12 skills in `~/.claude/skills/`
4. Adds this checkout as the `research-agent` marketplace and installs `research-agent@research-agent`. The marketplace lists only Research-Agent itself.
5. Creates `~/.research-agent/`: machine config, the global knowledge base, and a venv. The venv holds the skills' Python libraries and the `ra` CLI, installed from this checkout, so keep the checkout where it is.
6. Does what ARIS's `/aris:setup` would do:
   - points `~/.aris/repo` at ARIS
   - registers the `claude-review` MCP server, a fresh-context Claude reviewer used by ARIS and the Reviewer agent
7. Runs `ra doctor --skills`.

Re-running the installer is safe, because finished steps are skipped. These options add more:

| Option | What it does |
|---|---|
| `--with-latex` | Installs TeX Live on Ubuntu; prints hints on Windows and macOS |
| `--with-drawio` | Prints a hint for installing draw.io |
| `--extras exa-py wandb ...` | Installs extra Python packages into the venv |
| `--reviewer codex` | Uses ARIS's cross-model Codex reviewer instead. Needs an OpenAI account, then `/aris:setup` |

Check the install at any time with `ra doctor --skills --live`.

**Updating.** To update Research-Agent, run `git pull`, then `claude plugin marketplace update research-agent` and `claude plugin update research-agent@research-agent`. Each skill repo updates through its own marketplace (`claude plugin update ...`) or `npx skills update`.

## Use it in a project

```
/research-agent:ra-init                         # declare raw data (read-only), sensitive data, IRB, budget
/research-agent:ra <goal> [--loop research|coding|full|none]
/research-agent:ra-status                       # plans, tasks, runs, reviews, approvals, knowledge queue, budget
/research-agent:ra-kb <query> | queue           # search knowledge / decide what goes to the global KB
/research-agent:ra-approve                      # review pending approvals
/research-agent:ra-loop <mode> <goal>
```

You can also run the orchestrator as the main agent: `claude --agent research-agent:orchestrator`.

Example goals:
- `/research-agent:ra survey eye-tracking biomarkers for early Alzheimer's detection 2019–2026, comparison table + gaps --loop research`
- `/research-agent:ra propose 3 self-supervised scanpath representations for MCI screening and check novelty`
- `/research-agent:ra CPU pilot: logistic regression vs GRU on gaze features, subject-level 5-fold CV --loop coding`
- `/research-agent:ra draft Methods and Results for MICCAI from the passed runs, following CLAIM`
- `/research-agent:ra review paper.pdf as a TMI reviewer`

### Loops

| Mode | One iteration |
|---|---|
| `research` | research → methodology → reviewer |
| `coding` | coding → experiment (CPU smoke first) → reviewer |
| `full` | research → methodology → coding → experiment → reviewer |
| `none` | single pass (default) |

A loop stops when one of these happens:
- the reviewer returns PASS
- it reaches `max_loop_iterations` (3)
- the budget is exhausted
- the reviewer returns FAIL twice in a row

Every iteration writes `.research-agent/checkpoints/iter-N.md`, and the reviewer's MUST_FIX list carries into the next iteration.

### Headless (Claude Agent SDK)

```bash
~/.research-agent/venv/bin/pip install claude-agent-sdk
ra run --goal "..." --loop full --budget-usd 5       # or --dry-run to print the options
```

Nobody can approve anything in a headless run. Every action that would need approval is denied and listed in `.research-agent/approvals/pending.md`.

## Design principles, and how they are enforced

| Principle | Mechanism |
|---|---|
| Evidence-first | Claims carry `[SOURCED:key]`, `[RUN:id]`, `[INFERRED]` or `[HYPOTHESIS]`. `ra gate check` fails on unlabelled claims, unknown citation keys and unknown run ids. |
| Reproducibility-by-default | `ra job run` writes a manifest with git sha, dirty-diff hash, data hashes, config hashes, seed, environment, pip freeze and device. |
| Project isolation | Per-project `.research-agent/`. The guard denies reading another project's state. The knowledge base never searches another project. |
| Human-in-the-loop | The PreToolUse guard asks before sensitive data, publishing or pushing, cloud GPU, network sends, over-budget jobs and KB promotion. Writes to raw data are always denied. |
| Quality gates | Artifacts pass `ra gate check` and an independent fresh-context Reviewer verdict. A model saying "done" never counts. |
| Cost-aware | Three budget caps, limits on loops and subagents, and autonomy levels (see [docs/SAFETY.md](docs/SAFETY.md)). |

## Knowledge and memory

- **Global knowledge:** `~/.research-agent/knowledge/` (papers, notes, `library.bib`).
- **Project knowledge:** `.research-agent/kb/` and ARIS's `research-wiki/`.
- **Search:** both are searchable with SQLite FTS5 through `ra kb search`.
- **Promotion queue:** after every research, methodology or reviewer session, new project papers and notes are queued. The orchestrator then asks you which ones go to the global knowledge base. Nothing is promoted without your approval.
- **Project memory:** `.research-agent/memory/` holds decisions, progress and state. It is injected at session start.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/pytest -q
ra agents build     # after editing registry/*.toml or registry/prompts/*.md
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Hướng dẫn nhanh (Tiếng Việt)

1. **Cài một lần cho mỗi máy:** `python3 install.py`. Trên Windows dùng `py -3 install.py`.
   - Bộ cài cài 4 bộ skill đúng theo hướng dẫn của từng repo gốc. Chúng không nằm trong cache của Research-Agent.
   - Nếu máy có bản Tutu cũ, bộ cài hỏi bạn trước rồi mới gỡ.
2. **Trong mỗi project:** chạy `/research-agent:ra-init` để khai báo:
   - thư mục dữ liệu gốc (chỉ đọc)
   - dữ liệu nhạy cảm (đọc phải được duyệt)
   - mã IRB
   - ngân sách
3. **Giao mục tiêu:** `/research-agent:ra <mục tiêu> --loop research|coding|full|none`. Orchestrator lập kế hoạch, giao việc cho 6 agent chuyên môn, kiểm tra qua quality gate và Reviewer độc lập, rồi báo cáo.
4. **Ngân sách** có ba cấp:
   - `max_usd_per_session`: mỗi session
   - `max_usd_per_project`: toàn project
   - `max_gpu_usd_per_job`: mỗi experiment

   Bạn đặt các giá trị này trong `.research-agent/project.toml`.
5. **Kiến thức:** sau mỗi phiên research, methodology hoặc reviewer, orchestrator hỏi bạn paper hay ghi chú nào sẽ đưa vào global knowledge (`/research-agent:ra-kb queue`).
6. **Kiểm tra cài đặt:** `ra doctor --skills --live`.
