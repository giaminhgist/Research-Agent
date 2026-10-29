# Skills in Research-Agent

## Preload compatibility (spike, 2026-10-29, Claude Code 2.1.312)

A throwaway plugin agent declared `skills:` with one plugin skill (`superpowers:brainstorming`),
one bare user-level skill (`~/.claude/skills/<name>`), and two builtin skills (`code-review`, `dataviz`).

| How the agent runs | Result |
|---|---|
| Dispatched as a subagent (Agent tool) | All four were preloaded, including the user skill's body |
| As the main thread (`claude --agent plugin:agent`) | None were preloaded; only the SessionStart-injected skill was present |

Consequences:
- `BUILTIN_PRELOAD = True`: builtin skills go in `skills:` like any other.
- Bare names work for user-level skills (Supervisor-Skills installed to `~/.claude/skills`).
- When the orchestrator runs as the main thread (`/research-agent:ra` or `claude --agent research-agent:orchestrator`),
  its preload list is not applied. Its prompt therefore tells it to load its core skills with the Skill tool when needed.

## Allocation

Source of truth: `registry/agents.toml` (rendered into `agents/*.md` by `ra agents build`). **Core** skills are preloaded into the agent's context. **Borrowable** skills are offered by the skill resolver (`ra resolve "<task>" --agent <name>`) when the task calls for them. Any agent can still load any installed skill with the Skill tool: preloading is a default, not a fence.

Names are written as invoked: `aris:*`, `superpowers:*` and `humanizer:*` are plugin skills. Bare names are either Supervisor-Skills (installed user-level in `~/.claude/skills`) or Claude Code builtins (`code-review`, `security-review`, `simplify`, `dataviz`, `claude-api`, `loop`).

| Agent | Model | Core (preloaded) | Borrowable |
|---|---|---|---|
| **orchestrator** | opus | `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:dispatching-parallel-agents`, `superpowers:subagent-driven-development`, `superpowers:executing-plans`, `superpowers:verification-before-completion`, `aris:research-pipeline`, `aris:research-wiki`, `aris:render-html`, `vibe-research-workflow` | `loop`, `aris:research-refine-pipeline`, `superpowers:finishing-a-development-branch` |
| **research** | sonnet | `deep-research`, `aris:research-lit`, `aris:arxiv`, `aris:semantic-scholar`, `aris:openalex`, `aris:alphaxiv`, `aris:deepxiv`, `aris:research-wiki`, `aris:wiki-enrich`, `aris:citation-audit` | `aris:exa-search`, `aris:gemini-search`, `aris:keenable-search`, `aris:firecrawl-search`, `aris:novelty-check`, `aris:comm-lit-review` |
| **methodology** | opus | `aris:idea-discovery`, `aris:idea-creator`, `aris:novelty-check`, `aris:research-refine`, `aris:research-refine-pipeline`, `aris:experiment-plan`, `aris:ablation-planner`, `aris:formula-derivation`, `idea-evaluator`, `superpowers:brainstorming` | `aris:research-lit`, `aris:research-review`, `aris:proof-writer`, `aris:proof-checker`, `aris:idea-discovery-robot`, `aris:lean-formalize` |
| **coding** | sonnet | `superpowers:test-driven-development`, `superpowers:systematic-debugging`, `superpowers:using-git-worktrees`, `superpowers:requesting-code-review`, `superpowers:receiving-code-review`, `superpowers:verification-before-completion`, `aris:research-implement-feature`, `aris:experiment-bridge`, `aris:web-debug-search`, `simplify` | `code-review`, `security-review`, `superpowers:finishing-a-development-branch`, `aris:system-profile`, `claude-api` |
| **experiment** | sonnet | `aris:run-experiment`, `aris:experiment-queue`, `aris:monitor-experiment`, `aris:training-check`, `aris:analyze-results`, `aris:result-to-claim`, `aris:experiment-audit`, `aris:system-profile`, `dataviz`, `superpowers:verification-before-completion` | `aris:vast-gpu`, `aris:serverless-modal`, `aris:qzcli`, `aris:dse-loop`, `aris:paper-figure`, `aris:ablation-planner` |
| **writing** | opus | `aris:paper-writing`, `aris:paper-plan`, `aris:paper-write`, `aris:paper-figure`, `aris:paper-compile`, `aris:grant-proposal`, `aris:rebuttal`, `paper-writer`, `intro-drafter`, `paper-polish`, `humanizer:humanizer` | `tech-paper-template`, `benchmark-paper-template`, `rebuttal-guidance`, `figure-designer`, `drawio-reconstruction`, `aris:figure-spec`, `aris:mermaid-diagram`, `aris:paper-illustration`, `aris:paper-slides`, `aris:paper-talk`, `aris:paper-poster-html`, `aris:overleaf-sync`, `aris:auto-paper-improvement-loop`, `aris:resubmit-pipeline`, `aris:writing-systems-papers` |
| **reviewer** | opus | `aris:research-review`, `aris:experiment-audit`, `aris:paper-claim-audit`, `aris:citation-audit`, `aris:citation-crosscheck`, `aris:kill-argument`, `aris:integrity-forensics`, `aris:result-to-claim`, `pre-submission-reviewer`, `code-review` | `aris:auto-review-loop`, `security-review`, `rebuttal-guidance`, `aris:proof-checker`, `aris:novelty-check` |

## Installed but not mapped

These are installed by the upstream repos and remain usable through the Skill tool. They are not preloaded or offered by the resolver: they are outside the research scope (patents, interview prep, notifications), meta-tooling, deprecated, or alternative reviewer transports.

- `aris:auto-review-loop-llm`
- `aris:auto-review-loop-minimax`
- `aris:claims-drafting`
- `aris:embodiment-description`
- `aris:feishu-notify`
- `aris:figure-description`
- `aris:interview-cheatsheet`
- `aris:invention-structuring`
- `aris:jurisdiction-format`
- `aris:meta-apply`
- `aris:meta-optimize`
- `aris:paper-illustration-image2`
- `aris:paper-poster`
- `aris:patent-novelty-check`
- `aris:patent-pipeline`
- `aris:patent-review`
- `aris:pixel-art`
- `aris:prior-art-search`
- `aris:proof-orchestrator`
- `aris:slides-polish`
- `aris:specification-writing`
- `superpowers:diagnosing-superpowers`
- `superpowers:using-superpowers`
- `superpowers:writing-skills`
- `builtin:init`
- `builtin:run`
- `builtin:update-config`
- `builtin:fewer-permission-prompts`
- `builtin:workflow-authoring`
- `builtin:plugin-authoring`
- `builtin:keybindings-help`

## Skill dependencies

The resolver adds what a chosen skill needs. ARIS dependencies come from ARIS's own `tools/skill-groups.tsv`; others come from `depends_on` in `registry/skills_catalog.toml`. Skills that need an API key or a tool are reported as `missing` with the reason, for example `aris:exa-search` → `EXA_API_KEY` and `aris:paper-compile` → `latexmk`.

