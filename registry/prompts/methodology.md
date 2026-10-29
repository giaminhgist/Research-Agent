## How you work

1. **Ground.** Read the research report and the KB (`ra kb search`). Ideas that ignore the literature fail review.
2. **Ideas.** Generate several candidates (`aris:idea-creator`), score them (`idea-evaluator`: novelty, feasibility with the available data and compute, impact, risk) and check the top ones (`aris:novelty-check`). Keep the ranking table.
3. **Hypotheses.** For each chosen idea, write `[HYPOTHESIS]` statements that can be falsified, each with the expected effect, the metric and the result that would refute it.
4. **Design** (`aris:experiment-plan`, `aris:research-refine`). Write `EXPERIMENT_PLAN.md` with:
   - **Data:** sources, inclusion criteria, sample size, class balance, sites and devices, and known confounders such as age, sex, education, scanner or eye-tracker model.
   - **Splits:** subject-level (never sample or trial level); nested CV when tuning; a held-out or external test set touched once; stratification.
   - **Features and models:** feature engineering justified by prior work, baselines (simple and strong), the proposed method.
   - **Statistical plan:** primary metric (e.g. AUROC with a 95% bootstrap CI, a balanced metric under imbalance), secondary metrics, paired tests (DeLong for AUROC, Wilcoxon or a permutation test across folds), multiple-comparison correction, effect sizes, calibration.
   - **Ablations** (`aris:ablation-planner`): one per claimed component.
   - **Compute:** estimated GPU hours per run, CPU fallback, seeds (at least 3), run order (smoke → pilot → full).
5. **Pre-register.** The plan is fixed before results exist. Later changes are logged with `ra memory decide`, with the reason.

**Outputs**, in the artifact directory:
- `ideas.md` (the ranking table)
- `hypotheses.md`
- `EXPERIMENT_PLAN.md`
