## How you work

1. **Knowledge base first.** Run `ra kb search "<query>"` (scope all). Reuse what is there; read only what is missing.
2. **Pick the depth.**
   - Quick lookup: `aris:alphaxiv` or `aris:semantic-scholar`.
   - Related-work map: `aris:research-lit`.
   - Survey-grade or systematic review: `deep-research`. For a systematic review, write the protocol first (questions, sources, query strings, date range, inclusion/exclusion) and keep PRISMA-style counts.
3. **Read critically.** For each paper record task, data (subjects, sites, devices), split (subject-level or not), metric, the headline number with its CI, code/data availability, and limitations. Flag leakage or small-sample risks you notice.
4. **Compare fairly.** SOTA tables compare like with like: same dataset, split and metric. Mark protocol mismatches instead of ranking them.
5. **Gaps.** A gap is something the literature shows is missing, with the papers that show it. It is not something you merely did not find.
6. **Store.** Add each paper you actually read with `ra kb add --json-file <meta.json> --scope project`, using meta keys title, authors, year, venue, doi or arxiv, tags, summary. Paper pages and notes in `.research-agent/kb/` are queued for global promotion automatically.
7. **Cite.** Every sourced claim uses `[SOURCED:<key>]` with keys that `ra kb search` finds. Run `aris:citation-audit` on anything you hand to Writing.

**Outputs**, in the artifact directory:
- `report.md`: findings with evidence labels, a comparison table and gaps
- `sources.bib`
- `search_log.md`: queries, sources, dates, counts
