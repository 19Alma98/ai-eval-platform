# TODO

Open items from the RAG evaluation review (2026-10-08). Fixed items are in git history.

## Tooling

- [ ] **ESLint does not start.** `frontend/eslint.config.mjs` wraps `next/core-web-vitals` and
  `next/typescript` in `FlatCompat.extends(...)`, but `eslint-config-next` 16 already ships flat
  configs; ESLint crashes while validating the config ("property 'react' closes the circle"), so no
  file is linted. Fix: import the flat configs directly
  (`import nextVitals from "eslint-config-next/core-web-vitals"`, same for `typescript`) and drop
  `FlatCompat`.
- [ ] **No frontend `test` script.** Unit tests use `node:test` and only run with
  `node --import tsx --test <files>`. Add `"test"` to `frontend/package.json` and run it in CI.
- [ ] **Postgres-only paths not verified for the latest fixes.** Run the `*_postgres` suites with the
  DB up, covering: live-interaction `offset` paging + `(created_at, id)` ordering, `escape_like` with
  `ILIKE ... ESCAPE`, and the unique-violation recovery in `EnsureProjectDefaultMetricsSet` /
  `find_or_create_evaluator_for_entry` (real `IntegrityError` + session rollback).

## Evaluation correctness

- [ ] **hit@k with `expected_doc_ids: []` always FAILs** (`evaluation/deterministic.py`,
  `HitAtKEvaluator`). An empty gold set should be SKIPPED, not a retrieval failure.
- [ ] **Judge is not calibrated.** Live reviews (agree/disagree) are stored but never used. Report
  judge/human agreement (per kind, per judge model) so judge scores can be trusted or tuned.
- [ ] **Retrieval metrics are binary only.** Add recall@k and MRR (and optionally context
  precision); hit@k hides partial recall.
- [ ] **Regression gate has no significance test.** `DELTA_THRESHOLD = 0.01`
  (`regression/aggregate.py`) is noise on small test sets. Add a minimum item count and/or a
  bootstrap confidence interval on the delta before calling it a regression.
- [ ] **Legacy runs without `config_hash` are assumed comparable** in compare/release. Consider
  flagging them as "config unknown" once enough runs carry the hash.

## Performance

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row. Batch-load scores
  and reviews for a page.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL.
