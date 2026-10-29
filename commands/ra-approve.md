---
description: Review and grant pending Research-Agent approvals (sensitive data, publishing, cloud GPU, large jobs, knowledge promotion)
---

1. Run `ra approve list --json` (if `ra` is not on PATH use `~/.research-agent/venv/bin/ra`).
2. If there is nothing pending, say so and stop.
3. Otherwise ask the user with AskUserQuestion which to approve (show rule, target and reason; explain the risk in plain words).
4. For each approved item run `ra approve grant <rule> "<target>" --ttl <hours>` (default 24 h). Never grant anything the user did not choose.
