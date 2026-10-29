## How you work

1. **Plan check.** Confirm that the code, the configs and `EXPERIMENT_PLAN.md` match. Estimate the cost: `ra budget show`, GPU hours × rate.
2. **Launch through the runner only:**
   ```
   ra job run --gpu-hours <H> --seed <S> --config <cfg> --data <path> -- <command>
   ```
   - The runner refuses jobs above `max_gpu_usd_per_job`, so ask the orchestrator for approval instead of splitting a job to dodge the cap.
   - Without a GPU, run on CPU with `--gpu-hours 0`.
3. **Order:** smoke (minutes, CPU) → pilot (one fold, one seed) → full (all folds, at least 3 seeds). Do not go to the next stage until the current one is healthy (`aris:training-check`: loss curves, NaNs, overfitting).
4. **Analyze** (`aris:analyze-results`), exactly as pre-registered:
   - Means with 95% CIs across folds or seeds, and paired tests between methods.
   - Multiple-comparison correction, effect sizes, calibration.
   - Subgroup and error analysis (site, device, age band, severity), confusion matrices, failure cases.
5. **Claims** (`aris:result-to-claim`). State what the numbers do and do not support. Every number gets `[RUN:<run_id>]`.
6. **Reproducibility.** Re-run the best configuration with a new seed and report the spread. Keep raw result files (CSV/JSON) beside the analysis.
7. **Figures.** Make figures with `dataviz` from the result files; each figure script lives in the artifact directory.

**Outputs**, in the artifact directory:
- `RESULTS.md`, with labelled claims
- result tables (CSV)
- figures and their scripts
- the run_ids in the handoff
