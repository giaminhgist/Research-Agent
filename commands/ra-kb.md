---
description: Search the Research-Agent knowledge base (global library + this project), or review the global-promotion queue
argument-hint: "<query> | queue"
---

If `$ARGUMENTS` is `queue`:
1. Run `ra kb queue --json`.
2. Ask the user with AskUserQuestion (multiSelect, at most 4 items per question; title and one line each) which items to promote to the global knowledge base.
3. Run `ra kb promote --ids <chosen> --approved` and `ra kb dismiss --ids <the rest>`.

Otherwise run `ra kb search "$ARGUMENTS" --json` and present the hits grouped by scope (project, global) with title, path and the matching snippet. Offer to open the most relevant page.
(If `ra` is not on PATH use `~/.research-agent/venv/bin/ra`.)
