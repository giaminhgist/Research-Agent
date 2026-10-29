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
