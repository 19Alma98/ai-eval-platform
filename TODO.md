# TODO

Open items from the RAG evaluation review (2026-10-08). Fixed items are in git history.

## Tooling

- [ ] **No frontend `test` script.** Unit tests use `node:test` and only run with
  `node --import tsx --test <files>`. Add `"test"` to `frontend/package.json` and run it in CI.

## Evaluation correctness

- [ ] **Judge is not calibrated.** Live reviews (agree/disagree) are stored but never used. Report
  judge/human agreement (per kind, per judge model) so judge scores can be trusted or tuned.
- [ ] **Retrieval metrics are binary only.** Add recall@k and MRR (and optionally context
  precision); hit@k hides partial recall.
- [ ] **Regression gate has no significance test.** `DELTA_THRESHOLD = 0.01`
  (`regression/aggregate.py`) is noise on small test sets. Add a minimum item count and/or a
  bootstrap confidence interval on the delta before calling it a regression.

## Judge warnings

- [ ] **Live "judge model unsuitable" banner is computed in the browser** over the rows on screen
  (`liveUnsuitableRate` in `frontend/features/judges/judge-metadata.ts`, used by
  `live-run-list.tsx`). It pools all kinds and follows the active filters, so with "failed only" or
  `judge_status=error` the rate is inflated and the banner fires even when the project's real rate
  is low. Compute it in the backend over the last 50 live scores per kind (unfiltered) and return
  it from the list endpoint.
- [ ] **Compare has no run-level "judge model unsuitable" badge.** Only experiment detail shows it
  (`runJudgeWarning`); compare shows a per-item "judge output invalid" note because the compare
  endpoint does not return run metadata. Expose the baseline/candidate run warnings in the compare
  response and badge them next to the config-mismatch flag.

## Performance

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row. Batch-load scores
  and reviews for a page.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL.
