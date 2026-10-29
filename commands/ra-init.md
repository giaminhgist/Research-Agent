---
description: Make the current directory a Research-Agent project (raw data, sensitive data, IRB, budget)
argument-hint: "[--protected PATHS] [--sensitive PATHS] [--irb ID] [--budget-session USD] [--budget-project USD]"
---

Initialise this directory as a Research-Agent project.

1. If `$ARGUMENTS` does not already say so, ask the user (one AskUserQuestion, up to 4 questions):
   - which paths hold raw data that must never be modified;
   - which paths hold sensitive or identifiable data (reading them will need approval);
   - the IRB / ethics approval id, if any;
   - the budget per session and for the whole project in USD (defaults 10 and 100).
2. Run `ra init --protected <paths> --sensitive <paths> --irb <id> --budget-session <x> --budget-project <y>` (if `ra` is not on PATH use `~/.research-agent/venv/bin/ra`).
3. Show `ra status` and explain in three lines what was created: `.research-agent/` (plans, tasks, runs, reviews, approvals, knowledge base, memory), `project.toml`, and `.aris/reviewer.json` (ARIS reviews go to the fresh-context Claude reviewer).
