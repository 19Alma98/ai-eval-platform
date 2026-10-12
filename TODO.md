# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

## Before publishing on PyPI

- [ ] **Authentication.** No auth at all today. At minimum an API key for `/api/v1/*` and
  `/v1/traces`; people will expose it once it is on PyPI.
- [ ] **Judge model config.**
  - Document a minimum judge. `gemma4:e2b` discriminates well but returned invalid JSON on
    2/8 groundedness items in the hallucination test.

## Robustness

- [x] **Async scoring.** `evaluate` / `evaluate-pack` return 202; clients poll experiment status.
- [x] **Experiment stuck in `running`.** `EvaluateExperiment` marks `failed` + orphan runs on crash;
  startup recovery fails leftover `running` experiments.
- [x] **Live interactions stuck in `pending`.** Lifespan re-queues `pending`/`running` live scores.

## Evaluation correctness / design

- [x] **Test set versioning.** After the first evaluation run, add/import/promote auto-forks
  `name` v{N+1} (copied items + new write). Stale-run filtering kept for experiment output changes.
- [x] **Chunks from the same doc are dropped.** `_dedupe_by_id` in `evaluation/trace_context.py`
  keeps only the first chunk per doc id, so groundedness/context judges see partial context in
  chunked RAG. Dedupe ids for hit@k/MRR only; keep all texts for the judges.
- [x] **Compare has no statistics.** Paired bootstrap 95% CI on item diffs; n=8 one-flip stays
  `unchanged` with delta shown (not false `regression`).
- [x] **Release gate passes regression on `insufficient_n`.** Default: check `unavailable`
  (gate fails). Opt-in `regression.allow_insufficient_n: true` soft-passes for small demos.
- [x] **Latency p95 ignores missing-output items** (no `latency_ms` in metadata).
  Missing-output without `latency_ms` fails `latency.p95`; SKIPPED rows stay excluded.
- [x] **Live groundedness with no documents → FAIL 0.** Live: SKIPPED; offline keeps FAIL 0.
- [ ] **Claim cache stores empty extractions forever** (first write wins): one bad extraction makes
  correctness permanently SKIPPED (`no_gold_claims`) for that item/model/prompt.
- [ ] **Compare-items drill-down** (`compare_items.py`) does not apply the stale-run filter yet.
- [ ] **Default metrics set differs between projects.** One demo project got a 5-entry pack,
  a new one got 10 entries (`DEFAULT_RAG_SET_ENTRIES`). Verify `metrics-pack/ensure` vs
  dataset-creation ensure.

## Judge validation (meta-eval)

Synthetic runs with known truth on the 8-item gold set, judge `gemma4:e2b`:

| variant | correctness | groundedness | answer_relevance | hit@k | context_recall |
|---|---|---|---|---|---|
| good | 0.86 | 1.0 | 1.0 | 1.0 | 1.0 |
| wrong_fact | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 |
| hallucination | 1.0 | 0.35 (2 err) | 0.94 | 1.0 | 1.0 |
| bad_retrieval | 0.86 | 0.0 | 1.0 | 0.0 | 0.0 |

- [ ] Run the missing **refusal** variant and the **live** mode (groundedness + answer_relevance).
- [ ] Turn the meta-eval into a repo script / optional CI job (judge sanity suite) so judge or prompt
  changes are checked against known-good/known-bad answers.
- [ ] Demo gold set is weak: `expected_output` is only the `must_contain` phrase and n = 8.
  Write full reference answers and more items.
- [ ] Check `examples/hr_it_assistant/knowledge.json` encoding.

## Tooling

- [ ] **No frontend `test` script.** Unit tests use `node:test` and only run with
  `node --import tsx --test <files>`. Add `"test"` to `frontend/package.json` and run it in CI.
- [ ] **UI packaging tests fail locally** without a packaged UI
  (`test_sqlite_smoke.py::test_sqlite_ui_index_served`, `test_ui_resolve.py::test_ui_root_detects_packaged_index`).
  Skip them when the UI is not built.


## Performance

Deferred until list latency, DB pool pressure, or large projects make them hurt.
Do not block feature work on these. When optimizing, do N+1 batching first, then
`failed_only` denormalization (batching alone does not remove O(N) failed_only scans).

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row (~3 queries ×
  page size; default 50, polled every 5s). Batch-load scores and reviews for a page.
  Fix when: list feels slow or query volume / pool wait shows up under normal browsing.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL. Fix when: thousands+ interactions and the filter is used often (or empty full scans hurt).
  Do not replace with a fixed recent window — older failures must still surface.
