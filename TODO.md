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

## Ragas / DeepEval adapters

`aiobs.integrations.ragas` / `.deepeval` (2026-10-13) are tested only against fake modules: neither
library is installed, so `test_real_ragas_sample_accepts_our_fields` and
`test_real_deepeval_case_accepts_our_fields` are skipped.

- [ ] **Verify against the real libraries.** Install `aiobs-eval[ragas]` and `aiobs-eval[deepeval]`
  and run one real metric each end to end (e.g. `Faithfulness`, `AnswerRelevancyMetric`) with a
  local judge. Check what the fakes assume: Ragas `required_columns` format (incl. `:optional`),
  DeepEval `_required_params` / `evaluation_params`, the `a_measure` kwargs (`_show_indicator`,
  `_log_metric_to_confident`), judge model name extraction for `config["llm"]`.
- [ ] **Run the real-library tests in CI** (a job with both extras), so a library upgrade that breaks
  the mapping fails a build instead of every item turning ERROR.
- [ ] Known limits, decide if worth lifting: Ragas multi-turn metrics unsupported; DeepEval
  lower-is-better metrics (Bias, Toxicity, Hallucination, PIILeakage) rejected; `GEval` without
  `evaluation_steps` regenerates steps per item; DeepEval `context` / `tools_called` not mapped.

## Tooling

- [ ] **UI packaging tests fail locally** without a packaged UI
  (`test_sqlite_smoke.py::test_sqlite_ui_index_served`, `test_ui_resolve.py::test_ui_root_detects_packaged_index`).
  Skip them when the UI is not built.

## Cleanup

- [ ] **Remove interaction-level `LiveReview`.** Superseded by per-score `LiveScoreReview`; kept
  only "for compatibility", but nothing is shipped yet. Drop the DB model + migration (drops the
  table), domain, repository, `POST .../live-interactions/{id}/review`, `frontend/lib/api/live-runs.ts`
  usage, SDK and docs (`02-domain-model.md`, `05-api.md`). Also reword the "Legacy pack view"
  comment in `frontend/lib/api/metrics-packs.ts` (the code is still used).

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
