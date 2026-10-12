# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

## Before publishing on PyPI

- [ ] **Authentication.** No auth at all today. At minimum an API key for `/api/v1/*` and
  `/v1/traces`; people will expose it once it is on PyPI.

## Judge validation (meta-eval)

Synthetic runs on the 12-item HR gold set, judge `gemma4:e2b`, content-hashed prompts + format
repair (2026-10-12). Thresholds: `examples/hr_it_assistant/judge_sanity_thresholds.yaml`.

| variant | correctness | groundedness | answer_relevance | hit@k | context_recall |
|---|---|---|---|---|---|
| good | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| wrong_fact | 0.17 | 0.08 | 1.0 | 1.0 | — |
| hallucination | 1.0 | 0.58 | 0.83 | 1.0 | 1.0 |

- [ ] Run the missing **refusal** variant and the **live** mode (groundedness + answer_relevance).

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
