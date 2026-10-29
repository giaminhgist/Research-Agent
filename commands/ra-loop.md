---
description: Run the Research-Agent orchestrator in a loop mode (research | coding | full | none)
argument-hint: "<research|coding|full|none> <goal>"
---

The first word of `$ARGUMENTS` is the loop mode and the rest is the goal. The loops are:

| Mode | One iteration |
|---|---|
| research | research → methodology → reviewer |
| coding | coding → experiment (CPU smoke first) → reviewer |
| full | research → methodology → coding → experiment → reviewer |
| none | one pass, no repetition |

The loop stops on reviewer PASS, `max_loop_iterations` (default 3), the budget cap, or 2 consecutive FAILs.

Run `ra agents show orchestrator` and follow those instructions with this goal and `--loop <mode>`; use `ra loop start/next/verdict/checkpoint/status` to drive the loop, and show the user a checkpoint summary after every iteration.
