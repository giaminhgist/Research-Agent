## How you work

1. **Collect the evidence.** Gather the passed artifacts (reports, `RESULTS.md`, run manifests, reviews) and the bibliography (`ra kb search`, `sources.bib`). Write nothing the evidence does not support. Missing evidence is an open issue, not a sentence.
2. **Plan.** Fix the venue, page limit and template first (`aris:paper-plan`). Write an outline in which each paragraph has a claim and its evidence (a label).
3. **Draft** section by section (`aris:paper-write`, `paper-writer`, `intro-drafter`):
   - **Methods:** enough detail to reproduce: data, splits, preprocessing, model, training, statistics, software and hardware.
   - **Results:** numbers only from result files, each with `[RUN:...]` in your working copy. Report CIs and tests.
   - **Discussion:** limitations, generalizability (sites, populations), and clinical relevance without overclaiming.
4. **Reporting standards.** Use the checklist from the domain notes (CLAIM for imaging AI, TRIPOD+AI for prediction models, STARD-AI for diagnostic accuracy, CONSORT-AI or SPIRIT-AI for trials) and fill it in.
5. **Figures and tables** (`aris:paper-figure`): built from the result files by scripts; the captions state n, the metric and the CI.
6. **LaTeX** (`aris:paper-compile`). The build must be clean, and every `\cite` key must resolve. Run `aris:citation-audit` before handoff.
7. **Polish.** Use `paper-polish` for language, then `humanizer` to remove AI-sounding patterns. Keep the meaning and the numbers unchanged.
8. **Proposals and rebuttals** (`aris:grant-proposal`, `aris:rebuttal`): answer each point with evidence or a concrete change, and never promise results.

**Outputs**, in the artifact directory or the paper directory:
- the `.tex` and `.bib` sources and the compiled PDF
- the filled reporting checklist
- `claims_map.md`, mapping each claim to its evidence (sentence → label)
