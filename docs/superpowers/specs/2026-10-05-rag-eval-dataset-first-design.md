# RAG Evaluation — Dataset-First Vertical

Date: 2026-10-05  
Status: draft (awaiting user review)  
Approach: Same domain entities, product/UX reframe + RAG schema gaps (Approach 1)  
Related:
- `docs/00-project-overview.md` (RAG/FAQ as primary fit)
- `docs/02-domain-model.md` (Dataset, Experiment, Evaluator, AppConfig)
- `docs/03-evaluation-engine.md` (judges: groundedness, answer_relevance, correctness)
- `2026-10-02-frontend-ux-quality-loop-design.md` (trace-first loop — superseded for RAG vertical)
- `2026-10-02-hr-it-assistant-portfolio-design.md` (demo; update after this design)

## Problem

The platform already supports a quality loop (traces → datasets → experiments → compare → release) and a soft `task_type=rag_qa`, but the product reads as a **generic observability + eval console**. For a vertical **RAG evaluation** product:

1. The FE guides users to start from **production-style traces**, not from a fixed exam (test set) and scoring rules.
2. Traces and experiments feel similar (both are “lists of runs”) because the narrative does not separate **exam** vs **scoring session** vs **per-item execution proof**.
3. RAG-specific data and metrics are incomplete: retrieved documents are not promoted into eval `context`; there is no `hit@k` / expected doc gold; groundedness skips when context is missing; the portfolio demo scores with `contains` rather than the RAG pack.

## Goals

- Make the primary workflow **dataset-first**: project → test set → metrics → run → compare / release gate.
- Treat a RAG evaluation as: fixed test set + project metrics pack + SDK-instrumented runs bound to `run_id` + `dataset_item_id`.
- Require gold fields needed for retrieval and answer scoring (`question`, `expected_answer`, `expected_doc_ids`).
- Ship a default **RAG metrics pack** (hit@k, groundedness, correctness, latency) with editable thresholds and optional custom evaluators.
- Keep per-item **execution timeline** (retrieve / generate / latency / errors) under a run item for debugging low scores — not as a top-level “production traffic” product.
- Prefer FE/nav and domain extensions that reuse Dataset / Experiment / Evaluator / OTLP where possible.

## Non-goals

- Promoting production / live traffic into the test set (“add this real user question to the exam”).
- A separate “Observe production” product mode (possible later, unrelated to this vertical).
- In-platform RAG execution engine (no embedded retrieve/generate runner).
- Human review UI (roadmap Phase 5).
- Claim-level citation / faithfulness beyond whole-answer groundedness.
- Renaming backend packages or dropping classification / agent_tools task types from the core (they stay; they are not the product pitch).
- Built-in auth / multi-tenant SaaS.

## Product model

### Mental model

| Concept | Role | Analogy |
|---------|------|---------|
| **Test set** | Immutable exam for a version | Written exam sheet |
| **Metrics pack** | How that exam is graded | Answer key + rubrics |
| **Run** | One grading session on one test-set version | Correcting that exam with a given model/config |
| **Item execution / timeline** | Proof of how one question was answered | Student’s working for one exercise |

### User flow (FE)

After project creation:

1. **Test set** — create/import (CSV/JSON) and version.
2. **Metriche** — RAG default pack + thresholds + optional custom evaluators.
3. **Runs** — create a run pinned to `dataset` + version; execute via external app + SDK; score with pack.
4. **Confronta** / **Release** — compare runs on the same dataset+version; CI gate uses pack thresholds.

Navigation (replace quality-loop strip for this vertical):

`Test set → Metriche → Runs → Confronta → Release`

- **Traces** is not a loop step. Per-item OTLP timeline is reachable from **Run → item detail**.
- Overview becomes a setup checklist for this flow (test set present? metrics configured? at least one scored run?).

### Test set contract

- Soft type remains / emphasizes `rag_qa`.
- Each item **must** include:
  - `question` (mapped to `input` or a structured input object — implementation chooses one canonical shape and documents it)
  - `expected_answer` (mapped to `expected_output`)
  - `expected_doc_ids` (non-empty list; stored in a dedicated field or under a fixed `context`/`metadata` key — see Open decisions resolved below)
- Import (CSV and JSON) and manual create reject rows missing any required field.
- `actual_output` and retrieved documents are **not** part of the test set; they belong to the run.
- Versioning: editing items that change exam content creates or requires a **new dataset version**. A run always pins one version; mid-run dataset swap is forbidden.

**Resolved:** `expected_doc_ids` is required and non-empty for every item in a `rag_qa` test set used by this vertical.

### Metrics pack (project-scoped)

On first RAG setup (first `rag_qa` test set or explicit “enable RAG metrics”), create a project-level pack with defaults:

| Metric | Measures | Inputs |
|--------|----------|--------|
| **hit@k** | At least one expected doc id appears in top-k retrieved ids | `expected_doc_ids` + run retrieval ids; `k` configurable |
| **groundedness** | Answer supported by retrieved chunks | run retrieved text/snippets + `actual_output` |
| **correctness** | Alignment with gold answer | `expected_answer` + `actual_output` |
| **latency** | Per-item or aggregate latency vs threshold | execution timeline / context.latency_ms |

Rules:

- Defaults are **not removable** from the pack; they may be disabled or have thresholds changed.
- Custom evaluators may be **added** to the pack.
- Pack is **project-scoped** (same grading rules across test sets unless later extended). Threshold edits apply to **subsequent** runs only; past runs keep recorded scores/config hashes.
- Release gate binds to pack thresholds (YAML/policy may reference the same metric names).

### Run + SDK (execution mode B)

The platform does **not** run retrieve/generate. The user’s Python app (decorators / SDK) does.

Lifecycle:

1. Create run: name, pinned `dataset_id` + version, optional `app_config` / model snapshot.
2. Status: `draft` → `running` → `scored` (names may map to existing experiment statuses).
3. External app loads items for that dataset version; for each item executes retrieve + generate under SDK instrumentation.
4. Every evaluation execution **must** carry **`run_id` + `dataset_item_id`**. Spans or upserts without that binding are ignored for scoring (out of scope for this vertical).
5. Platform records per item: `actual_output`, retrieved documents (ids + text/snippets used for groundedness), and execution timeline (retrieve/generate spans, latency, errors).
6. When the set is complete (or on explicit “score” action), apply the project metrics pack.
7. Compare only runs that share the same dataset+version. Release check uses pack thresholds.

UI rename: **Experiments → Runs** in the RAG console. Backend may keep `Experiment` entities.

### Per-item execution detail

For each scored (or running) item, the run detail shows:

- question, expected answer, expected doc ids  
- retrieved docs, model answer  
- metric scores + explanations  
- **timeline**: retrieve / generate steps, timings, errors (from bound OTLP spans)

This is exam working papers, not a production traffic explorer.

## Mapping to current codebase

| Product concept | Current artifact | Change |
|-----------------|------------------|--------|
| Test set | `Dataset` + `DatasetItem` | Enforce `rag_qa` required fields; CSV/JSON import |
| Expected docs | missing as first-class gold | Add storage + import columns |
| Metrics pack | loose `Evaluator` list + release YAML | New project pack entity or composed registry + defaults |
| hit@k | missing | New deterministic evaluator |
| groundedness context | `build_eval_context_from_trace` omits documents | Extract retrieval docs into run item context |
| Run | `Experiment` + `ExperimentItemOutput` | Bind `run_id`+`item_id` from SDK; UI rename |
| Timeline | Trace/span UI | Embed under run item; demote top-level Traces from loop |
| FE loop strip | Traces → Datasets → … | Test set → Metriche → Runs → Confronta → Release |

## Error handling

- Import validation: fail the whole file or row-report with line numbers; no silent drop of required columns.
- Score skip/error: keep existing evaluator semantics (`SKIPPED` / `ERROR` must not become score 0 silently).
- Unbound spans during a run: do not attach to items; optional operator log/metric later.
- Compare across different dataset versions: reject with a clear API/UI error.

## Testing (design-level)

- Unit: hit@k; import schema validation; pack default creation; threshold immutability for past runs.
- API: create run pinned to version; upsert output with retrieval docs; score applies pack; compare same-version only.
- SDK: decorator/attribute path that sets `run_id` + `dataset_item_id` and retrieval document payloads.
- FE: empty states follow Test set → Metriche → Runs; no promote-from-traffic CTA in this vertical.
- Update portfolio demo to use RAG pack (hit@k + judges) with required gold fields, not only `contains`.

## Open questions (deferred, not blockers)

- Exact CSV column names (`question` vs `input`) — fix in implementation plan with one canonical mapping table.
- Whether `answer_relevance` joins the default pack or stays optional custom — default pack stays the four metrics above unless product revisits.
- Persistence shape of metrics pack (new table vs JSON on project) — implementation plan.

## Self-review notes

- No TBD placeholders left for scope decisions already closed with the user.
- Production-trace promote explicitly out of scope.
- Approach 1 chosen: reframe + fill RAG gaps; no new “EvaluationSession” entity required for v1.
- Scope is one vertical workflow + supporting backend/SDK/FE; suitable for a single implementation plan broken into phased tasks.
