# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

## Before publishing on PyPI

- [ ] **Authentication.** No auth at all today. At minimum an API key for `/api/v1/*` and
  `/v1/traces`; people will expose it once it is on PyPI.
- [ ] **Judge model config.**
  - Document a minimum judge. `gemma4:e2b` discriminates well but returned invalid JSON on
    2/8 groundedness items in the hallucination test.

## Robustness

- [ ] **Async scoring.** `evaluate-pack` runs inside the HTTP request. With the 10-entry default
  set (5 LLM judges) the portfolio demo hit the 120s client timeout on 8 items. Move to a
  job/queue with status polling.
- [ ] **Experiment stuck in `running`.** `EvaluateExperiment` sets `running` and has no
  try/finally: any exception mid-scoring leaves it `running` forever.
- [ ] **Live interactions stuck in `pending`.** Scoring uses in-process `BackgroundTasks`; after
  an API restart nothing re-queues `pending`/`running` rows (only manual `rescore`).

## Evaluation correctness / design

- [ ] **Test set versioning.** Items can still be added after runs exist (API, CSV import, live
  promote). Stale runs are now detected and excluded, but the spec asks for immutable versions:
  block edits on a dataset with runs, or create a new version.
- [ ] **Chunks from the same doc are dropped.** `_dedupe_by_id` in `evaluation/trace_context.py`
  keeps only the first chunk per doc id, so groundedness/context judges see partial context in
  chunked RAG. Dedupe ids for hit@k/MRR only; keep all texts for the judges.
- [ ] **Compare has no statistics.** Fixed delta 0.01 with n >= 5. On 8 binary items one flip = 0.125
  = "regression". Add a paired test / bootstrap CI, or a larger min-n for judge metrics.
- [ ] **Release gate passes regression on `insufficient_n`.** Regression silently dropped when
  n < 5 (`release_check.py`). At least surface it as a warning; consider failing by default.
- [ ] **Latency p95 ignores missing-output items** (no `latency_ms` in metadata).
- [ ] **Live groundedness with no documents → FAIL 0.** OK for RAG; consider SKIPPED for
  interactions that never retrieved anything.
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
- [ ] Check `examples/hr_it_assistant/knowledge.json` encoding (`10:00�16:00` showed up in
  the terminal; may just be the console code page).

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
