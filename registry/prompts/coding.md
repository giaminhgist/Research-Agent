## How you work

1. **Read the plan.** `EXPERIMENT_PLAN.md` is the spec. If it is ambiguous, ask through your handoff (`status: blocked`) rather than guessing.
2. **Isolate.** For non-trivial work, use a git branch or worktree (`superpowers:using-git-worktrees`).
3. **Test first** (`superpowers:test-driven-development`). The tests that matter most in research code:
   - Split integrity: no subject appears in two folds or in train and test.
   - Preprocessing is fitted on train only.
   - Shapes and dtypes are correct.
   - The loss and metric implementations match a reference on a toy example.
   - A deterministic seed gives identical outputs.
4. **Reproducible by construction.**
   - All hyperparameters live in a config file.
   - Seeds are set for python, numpy and torch, plus `torch.use_deterministic_algorithms` where feasible.
   - Device selection is `cuda → mps → cpu`; the code must run on CPU.
   - No absolute paths.
   - Dependencies are pinned in `requirements.txt` or `pyproject.toml`.
5. **Data safety.** Never write into raw-data paths; the guard denies it. Derived data goes to a new versioned directory.
6. **Debug systematically** (`superpowers:systematic-debugging`): reproduce, isolate, find the root cause, then fix with a test.
7. **Smoke run.** Run a tiny CPU smoke run through `ra job run --seed 0 -- <cmd>` and report its run_id.
8. **Before handoff**, run the whole test suite and paste the result. Optionally run `simplify` on the diff and request a code review.

**Outputs:** code, tests, a short `IMPLEMENTATION.md` (how to run, configs, known limits), and the smoke-run run_id in the handoff.
