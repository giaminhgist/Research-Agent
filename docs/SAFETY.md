# Safety: guardrails, approvals and budget

Research-Agent is meant to run with a lot of autonomy, including headless overnight. Its guardrails are enforced in code, through Claude Code hooks and the headless SDK permission callback. They are not left to instructions in a prompt.

## Guard (PreToolUse hook → `guard.evaluate`)

Deny rules are checked first, then ask rules. An *ask* is shown to you as a permission prompt in interactive sessions. In headless runs it becomes a deny and is logged to `.research-agent/approvals/pending.md`.

| Rule | Decision | Trigger |
|---|---|---|
| `protected-write` | deny | Any write into `data.protected_paths` (raw data): Write/Edit tools, shell redirects, `tee`, `cp`/`mv`/`rsync` destinations, `rm`, `sed -i`, `dd of=`, and `cd` chains |
| `rm-outside` | deny | Recursive delete outside the project, or of `/`, `~` or the project root |
| `cross-project` | deny | Reading or writing another project's `.research-agent/` |
| `reviewer-scope` | deny | The reviewer writing anywhere but `.research-agent/reviews/` |
| `phi-read` | ask | Reading `data.sensitive_paths` |
| `publish` | ask | `git push`, `gh pr create/merge`, `gh release`, package publish, arXiv/OpenReview submit, Overleaf push |
| `cloud-gpu` | ask | `vastai`, `modal run/deploy`, `sbatch`, `qsub`, `srun`, `runpodctl` |
| `network-send` | ask | `curl` POST/PUT/upload, `wget --post`, `scp`, `sftp`, `rsync` to a remote host |
| `gpu-over-cap` | ask | `ra job run --gpu-hours H` with H × `gpu_usd_per_hour` > `max_gpu_usd_per_job` |
| `kb-promote` | ask | `ra kb promote` without `--approved` |
| `inline-protected` | ask | `python -c` / `perl -e` and similar inline scripts that mention a protected path |
| `supervised-job`, `supervised-install` | ask | Only in `autonomy.level = "supervised"`: every `ra job run` and every package install |

- Grants are time-limited, with a 24 h default: `ra approve grant <rule> [target] --ttl H`, or `/research-agent:ra-approve`.
- The autonomy level only adds asks. It never turns a deny into an allow, and it never removes the publish/cloud/PHI asks.
- Outside a Research-Agent project, only the universal deny rules apply.
- The shell analysis is best-effort. A determined script can still write files the parser cannot see, for example a Python script that opens a raw-data file for writing. For real protection, make raw data read-only at the filesystem level as well (`chmod -R a-w data/raw`).

## Budget: three tiers

| Cap | Scope | How it is enforced |
|---|---|---|
| `max_usd_per_session` | One Claude Code or Agent SDK session | Interactive: before every subagent dispatch, the PreToolUse hook computes the session cost from the transcript's token usage and the price table in `config/default.toml`. It warns at 80% and denies new dispatches at 100%. Headless: the SDK's `max_budget_usd`. |
| `max_usd_per_project` | All sessions and GPU jobs of a project | Stop/SessionEnd hooks write each session's cost to `.research-agent/budget.jsonl`. Dispatches are denied once the total reaches the cap. |
| `max_gpu_usd_per_job` | One experiment | `ra job run --gpu-hours H` estimates H × `gpu_usd_per_hour` before launch. Jobs over the cap are refused unless you approve and raise the cap. A job is killed after `cap / rate` hours, and its actual cost is recorded. |

Other limits:
- `max_loop_iterations` (3)
- `max_consecutive_fails` (2)
- `max_subagents_per_session` (20, enforced)
- `max_parallel_subagents` (3, advisory: hooks cannot observe parallelism)

If the transcript cannot be read, the session cost is unknown. Dispatch then continues with a warning, but the project cap is still enforced.

## Quality gates

`ra gate check <task>` passes only when:
1. the artifact directory has files;
2. a handoff block with a status exists;
3. every claim bullet carries an evidence label whose citation keys and run ids resolve;
4. every run_id in the handoff has a manifest;
5. for the final stage, the reviewer's file says `VERDICT: PASS` or `PASS_WITH_FIXES`.
