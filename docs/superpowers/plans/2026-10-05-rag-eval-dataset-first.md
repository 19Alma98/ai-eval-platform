# RAG Evaluation Dataset-First — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the platform’s primary product surface into a dataset-first RAG evaluation vertical: fixed test sets with required gold fields, a project metrics pack (hit@k + groundedness + correctness + latency), SDK-bound runs that record answers/docs/timeline, and a FE flow of Test set → Metriche → Runs → Confronta → Release.

**Architecture:** Reuse `Dataset` / `Experiment` / `Evaluator` / OTLP. Store gold doc ids in `DatasetItem.metadata["expected_doc_ids"]`. Store retrieved docs on `ExperimentItemOutput.context["documents"]`. Add project-scoped `MetricsPack` (JSONB entries + linked evaluator ids). SDK sets `aiobs.experiment_id` + `aiobs.dataset_item_id`; OTLP ingest upserts run outputs when both are present. FE renames the quality loop; Traces stay reachable only from run item detail.

**Tech Stack:** FastAPI, SQLAlchemy 2 async + Alembic, PostgreSQL JSONB, pytest/httpx, Python SDK (OpenTelemetry), Next.js App Router, TanStack Query, TypeScript.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-05-rag-eval-dataset-first-design.md`
- Domain must not import FastAPI/SQLAlchemy.
- Trusted network / no auth (unchanged).
- No production-trace → dataset promote in this vertical (keep API for now; remove/hide FE CTA).
- No in-platform RAG execution engine.
- Canonical `rag_qa` item shape:
  - `input`: `string` (question)
  - `expected_output`: non-empty `string` (expected_answer)
  - `metadata["expected_doc_ids"]`: non-empty `list[str]`
- Canonical run retrieval shape on `ExperimentItemOutput.context`:
  - `documents`: `list[{"id": str, "text"?: str, "title"?: str}]` (non-empty ids when present)
  - may also include `latency_ms`, tokens, etc.
- CSV/JSON import columns: `question`, `expected_answer`, `expected_doc_ids` (`expected_doc_ids` = JSON array string or `|`-separated ids).
- Metrics pack defaults (not removable; disable/threshold only): `hit_at_k`, `groundedness`, `correctness`, `latency`.
- Pack is project-scoped; threshold edits apply to subsequent scores only.
- Backend entity name stays `Experiment`; UI label is **Runs**.
- Status mapping: `created`≈draft, `running`, `completed`≈scored (reuse `EXPERIMENT_STATUSES`).
- OTLP bind attrs: `aiobs.experiment_id` (UUID string), `aiobs.dataset_item_id` (UUID string).
- Commit steps: only commit when the user asks (or when executing this plan after they approve commits). Otherwise leave the tree dirty and note “ready to commit”.
- Backend tests: `cd backend && uv run pytest …` (Postgres up for `*_postgres.py`). Frontend: `cd frontend && npm run typecheck`. SDK: `cd sdk && uv run pytest …`.

---

## File map

```text
backend/
  alembic/versions/0008_metrics_packs.py                 # CREATE
  src/aiobs/
    domain/
      rag_qa.py                                          # CREATE — validate/normalize rag items
      metrics_pack.py                                    # CREATE — MetricsPack entity
      repositories.py                                    # MODIFY — MetricsPackRepository
      task_types.py                                      # MODIFY — hints include expected_doc_ids, hit_at_k
    evaluation/
      deterministic.py                                   # MODIFY — HitAtKEvaluator + register
      trace_context.py                                   # MODIFY — extract retrieval documents
      __init__.py                                        # unchanged bootstrap (hit_at_k via deterministic)
    application/
      datasets.py                                        # MODIFY — validate rag_qa items; import use case
      metrics_packs.py                                   # CREATE — ensure/get/patch pack; score-from-pack
      evaluate.py                                        # MODIFY — optional evaluate via pack
      compare.py                                         # MODIFY — same dataset_id guard (version via dataset)
      experiment_outputs.py                              # MODIFY — normalize documents in context
    tracing/
      run_binding.py                                     # CREATE — parse bind attrs → upsert payload
      ingestion.py                                       # MODIFY — return traces (hook stays in route)
    infrastructure/
      models.py                                          # MODIFY — MetricsPackModel
      repositories.py                                    # MODIFY — SQL repos
    api/
      schemas.py                                         # MODIFY
      deps.py                                            # MODIFY
      routes/datasets.py                                 # MODIFY — import endpoint; stricter items
      routes/metrics_packs.py                            # CREATE
      routes/otlp.py                                     # MODIFY — bind → upsert outputs
      routes/__init__.py                                 # MODIFY — include router
      routes/experiments.py                              # MODIFY — evaluate-pack; compare guard errors
  tests/
    test_domain_rag_qa.py                                # CREATE
    test_domain_metrics_pack.py                          # CREATE
    test_hit_at_k.py                                     # CREATE
    test_api_dataset_import.py                           # CREATE
    test_api_metrics_packs.py                            # CREATE
    test_api_otlp_run_binding.py                         # CREATE
    test_api_compare.py                                  # MODIFY — dataset mismatch
    test_api_evaluation.py                               # MODIFY — rag validation + pack score
    test_evaluation_engine.py                            # MODIFY — retrieval docs in context

sdk/
  src/aiobs/
    __init__.py                                          # MODIFY — export helpers
    _trace.py                                            # MODIFY — bind_evaluation, set_retrieval_documents
    _eval_run.py                                         # CREATE — thin helpers / docs in docstring
  tests/
    test_eval_bind.py                                    # CREATE

frontend/
  components/
    quality-loop-strip.tsx                               # MODIFY — new steps
    app-shell.tsx                                        # MODIFY — nav labels/order
  features/
    overview/overview-dashboard.tsx                      # MODIFY — checklist
    overview/loop-progress.tsx                           # MODIFY — card titles
    datasets/
      dataset-list.tsx                                   # MODIFY — “Test set” copy; import entry
      dataset-detail.tsx                                 # MODIFY — show expected_doc_ids; import UI
      import-dataset-dialog.tsx                          # CREATE
    metrics/
      metrics-pack-page.tsx                              # CREATE
      use-metrics-pack.ts                                # CREATE
    experiments/
      experiment-list.tsx                                # MODIFY — “Runs” copy
      experiment-detail.tsx                              # MODIFY — score pack CTA; item timeline
      run-item-timeline.tsx                              # CREATE
      create-experiment-dialog.tsx                       # MODIFY — copy
    traces/
      add-to-dataset-dialog.tsx                          # MODIFY — hide/remove from RAG loop (or keep but de-emphasized)
  app/(app)/
    metrics/page.tsx                                     # CREATE
  lib/api/
    types.ts                                             # MODIFY
    datasets.ts                                          # MODIFY — import
    metrics-packs.ts                                     # CREATE

examples/hr_it_assistant/
  knowledge.json                                         # MODIFY — ensure gold has doc id fields if needed
  main.py                                                # MODIFY — bind_evaluation + set_retrieval_documents
scripts/portfolio_demo.py                                # MODIFY — rag pack + required fields
docs/
  00-project-overview.md                                 # MODIFY — dataset-first pitch
  02-domain-model.md                                     # MODIFY — pack + rag fields
  03-evaluation-engine.md                                # MODIFY — hit_at_k
  05-api.md                                              # MODIFY — new endpoints
  07-frontend.md                                         # MODIFY — nav
```

---

### Task 1: RAG item validation (`rag_qa` gold contract)

**Files:**
- Create: `backend/src/aiobs/domain/rag_qa.py`
- Modify: `backend/src/aiobs/domain/task_types.py`
- Test: `backend/tests/test_domain_rag_qa.py`

**Interfaces:**
- Produces:
  - `EXPECTED_DOC_IDS_KEY = "expected_doc_ids"`
  - `def normalize_expected_doc_ids(value: Any) -> list[str]`
  - `def validate_rag_qa_item(*, input: Any, expected_output: Any, metadata: dict[str, Any]) -> dict[str, Any]`  
    Returns normalized metadata (with `expected_doc_ids`); raises `ValueError` with clear message if invalid.
- Consumes: none

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_domain_rag_qa.py
from __future__ import annotations

import pytest

from aiobs.domain.rag_qa import normalize_expected_doc_ids, validate_rag_qa_item


def test_normalize_pipe_and_list() -> None:
    assert normalize_expected_doc_ids("a|b") == ["a", "b"]
    assert normalize_expected_doc_ids(["x", "y"]) == ["x", "y"]


def test_validate_ok() -> None:
    meta = validate_rag_qa_item(
        input="What is PTO?",
        expected_output="20 days",
        metadata={"expected_doc_ids": ["pto-1"]},
    )
    assert meta["expected_doc_ids"] == ["pto-1"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input": "", "expected_output": "a", "metadata": {"expected_doc_ids": ["d"]}},
        {"input": "q", "expected_output": None, "metadata": {"expected_doc_ids": ["d"]}},
        {"input": "q", "expected_output": "a", "metadata": {"expected_doc_ids": []}},
        {"input": "q", "expected_output": "a", "metadata": {}},
    ],
)
def test_validate_rejects(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        validate_rag_qa_item(**kwargs)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd backend && uv run pytest tests/test_domain_rag_qa.py -v
```

Expected: `ModuleNotFoundError` or import error for `aiobs.domain.rag_qa`.

- [ ] **Step 3: Implement `rag_qa.py`**

```python
# backend/src/aiobs/domain/rag_qa.py
from __future__ import annotations

from typing import Any

EXPECTED_DOC_IDS_KEY = "expected_doc_ids"


def normalize_expected_doc_ids(value: Any) -> list[str]:
    if value is None:
        raise ValueError("expected_doc_ids is required")
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(",", "|").split("|") if p.strip()]
        if not parts:
            raise ValueError("expected_doc_ids must be non-empty")
        return parts
    if isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
        if not out:
            raise ValueError("expected_doc_ids must be non-empty")
        return out
    raise ValueError("expected_doc_ids must be a list or pipe-separated string")


def validate_rag_qa_item(
    *,
    input: Any,
    expected_output: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(input, str) or not input.strip():
        raise ValueError("rag_qa input (question) must be a non-empty string")
    if not isinstance(expected_output, str) or not expected_output.strip():
        raise ValueError("rag_qa expected_output (expected_answer) must be a non-empty string")
    ids = normalize_expected_doc_ids(metadata.get(EXPECTED_DOC_IDS_KEY))
    cleaned = dict(metadata)
    cleaned[EXPECTED_DOC_IDS_KEY] = ids
    return cleaned
```

- [ ] **Step 4: Update `task_types.py` hints** for `rag_qa` to mention `metadata.expected_doc_ids` and recommend `hit_at_k`.

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd backend && uv run pytest tests/test_domain_rag_qa.py -v
```

- [ ] **Step 6: Ready to commit** (message: `feat: add rag_qa item gold validation`)

---

### Task 2: Enforce validation on dataset item create

**Files:**
- Modify: `backend/src/aiobs/application/datasets.py`
- Modify: `backend/src/aiobs/api/routes/datasets.py` (map `ValueError` → 422)
- Test: `backend/tests/test_api_evaluation.py` (or new `test_api_rag_qa_items.py`)

**Interfaces:**
- Consumes: `validate_rag_qa_item`
- Produces: `AddDatasetItem` rejects invalid `rag_qa` items; non-`rag_qa` unchanged

- [ ] **Step 1: Write failing API test**

```python
async def test_rag_qa_item_requires_expected_doc_ids(client: AsyncClient) -> None:
    proj = (await client.post("/api/v1/projects", json={"name": "P", "slug": "p-rag"})).json()
    ds = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/datasets",
            json={"name": "faq", "task_type": "rag_qa"},
        )
    ).json()
    bad = await client.post(
        f"/api/v1/datasets/{ds['id']}/items",
        json={"input": "Q?", "expected_output": "A"},
    )
    assert bad.status_code == 422

    ok = await client.post(
        f"/api/v1/datasets/{ds['id']}/items",
        json={
            "input": "Q?",
            "expected_output": "A",
            "metadata": {"expected_doc_ids": ["doc-1"]},
        },
    )
    assert ok.status_code == 201
    assert ok.json()["metadata"]["expected_doc_ids"] == ["doc-1"]
```

- [ ] **Step 2: Run test — expect FAIL** (currently 201 without docs)

- [ ] **Step 3: In `AddDatasetItem.execute`**, after loading dataset, if `dataset.task_type == "rag_qa"`:

```python
from aiobs.domain.rag_qa import validate_rag_qa_item

meta = validate_rag_qa_item(
    input=command.input,
    expected_output=command.expected_output,
    metadata=dict(command.metadata or {}),
)
# use meta when creating DatasetItem
```

Map `ValueError` in the route to `HTTPException(422, detail=str(exc))`.

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Ready to commit** (`feat: enforce rag_qa gold fields on item create`)

---

### Task 3: CSV/JSON test-set import

**Files:**
- Create helpers in: `backend/src/aiobs/application/dataset_import.py`
- Modify: `backend/src/aiobs/application/datasets.py` or use new use case `ImportDatasetItems`
- Modify: `backend/src/aiobs/api/routes/datasets.py` — `POST /api/v1/datasets/{id}/items/import`
- Modify: `backend/src/aiobs/api/schemas.py` — request/response with row errors
- Test: `backend/tests/test_api_dataset_import.py`

**Interfaces:**
- Produces: `ImportDatasetItemsResult(created: int, errors: list[{row, message}])`
- Import policy: **row-report**; valid rows are created; invalid rows listed with 1-based row numbers; HTTP 200 with errors non-empty, or 422 if zero created and errors present (prefer: always 200 with `{created, errors}` so FE can show table — **use 200 + created/errors**; if `created==0` and `errors`, still 200).
- CSV required headers: `question,expected_answer,expected_doc_ids`
- JSON: array of objects with same keys

- [ ] **Step 1: Write failing tests** for CSV happy path + one bad row + missing header.

- [ ] **Step 2: Implement parser**

```python
# backend/src/aiobs/application/dataset_import.py (sketch)
import csv
import io
import json
from typing import Any

from aiobs.domain.rag_qa import validate_rag_qa_item

REQUIRED = ("question", "expected_answer", "expected_doc_ids")


def parse_import_payload(*, filename: str | None, raw: bytes) -> list[dict[str, Any]]:
    name = (filename or "").lower()
    text = raw.decode("utf-8-sig")
    if name.endswith(".json") or text.lstrip().startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("JSON import must be an array of objects")
        return data
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header")
    missing = [c for c in REQUIRED if c not in reader.fieldnames]
    if missing:
        raise ValueError(f"CSV missing columns: {', '.join(missing)}")
    return list(reader)


def row_to_item_fields(row: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    question = row.get("question")
    answer = row.get("expected_answer")
    meta = {"expected_doc_ids": row.get("expected_doc_ids")}
    meta = validate_rag_qa_item(input=question, expected_output=answer, metadata=meta)
    return str(question).strip(), str(answer).strip(), meta
```

Wire multipart or raw body: prefer `UploadFile` + optional `format` query. For each row index, try `row_to_item_fields` + `add_item`; collect errors.

**Note:** Import for `task_type != rag_qa` returns 400 for v1 of this plan (YAGNI).

- [ ] **Step 3: API route + tests PASS**

- [ ] **Step 4: Ready to commit** (`feat: import rag_qa test set from CSV/JSON`)

---

### Task 4: `hit_at_k` deterministic evaluator

**Files:**
- Modify: `backend/src/aiobs/evaluation/deterministic.py`
- Test: `backend/tests/test_hit_at_k.py`

**Interfaces:**
- Produces: registered kind `"hit_at_k"`
- Config: `{"kind": "hit_at_k", "k": 5}` (`k` default 5, must be >= 1)
- Reads:
  - expected ids: `sample.metadata["expected_doc_ids"]`
  - retrieved: `sample.context["documents"]` → list of dicts with `id`, **or** `sample.context["retrieved_doc_ids"]` list[str]
- Score: `1.0` if intersection of expected and top-`k` retrieved ids non-empty, else `0.0`
- Missing data → `SKIPPED` (not 0)

- [ ] **Step 1: Failing unit tests** (hit, miss, k truncation, skipped)

```python
# backend/tests/test_hit_at_k.py
import pytest
from aiobs.evaluation.deterministic import HitAtKEvaluator
from aiobs.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_hit_at_k_pass() -> None:
    ev = HitAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"documents": [{"id": "b"}, {"id": "a"}, {"id": "c"}]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label == "PASS"
```

- [ ] **Step 2: Implement `HitAtKEvaluator` + `register_evaluator("hit_at_k", HitAtKEvaluator)`**

- [ ] **Step 3: Tests PASS**

- [ ] **Step 4: Ready to commit** (`feat: add hit_at_k evaluator`)

---

### Task 5: Retrieval documents in eval context helpers

**Files:**
- Modify: `backend/src/aiobs/evaluation/trace_context.py`
- Create: `backend/src/aiobs/domain/retrieval.py` (normalize documents list)
- Test: `backend/tests/test_evaluation_engine.py` (extend)

**Interfaces:**
- Produces:
  - `def normalize_documents(value: Any) -> list[dict[str, Any]]`
  - `build_eval_context_from_trace` also sets `context["documents"]` from RETRIEVER span attributes:
    - prefer `retrieval.documents` (list of `{id, title?, text?}`)
    - fallback: any span attr already normalized
- Groundedness continues to use `sample.context` (documents + text). Ensure judge payload includes document texts when present.

- [ ] **Step 1: Failing test** — trace with RETRIEVER span attrs → `documents` in context

- [ ] **Step 2: Implement extraction**

```python
# in build_eval_context_from_trace, after scanning spans:
docs: list[dict[str, Any]] = []
for span in spans:
    if span.kind.upper() != "RETRIEVER":
        continue
    raw = (span.attributes or {}).get("retrieval.documents")
    if isinstance(raw, list):
        docs.extend(normalize_documents(raw))
    elif isinstance(raw, str):
        # JSON string from OTEL attribute serialization
        ...
if docs:
    context["documents"] = docs
```

- [ ] **Step 3: Tests PASS**

- [ ] **Step 4: Ready to commit** (`feat: extract retrieval documents into eval context`)

---

### Task 6: Metrics pack domain + persistence

**Files:**
- Create: `backend/src/aiobs/domain/metrics_pack.py`
- Create: `backend/alembic/versions/0008_metrics_packs.py`
- Modify: `backend/src/aiobs/domain/repositories.py`
- Modify: `backend/src/aiobs/infrastructure/models.py`
- Modify: `backend/src/aiobs/infrastructure/repositories.py`
- Test: `backend/tests/test_domain_metrics_pack.py`

**Interfaces:**
- Produces `MetricsPack`:
  - `id`, `project_id`, `entries: list[MetricsPackEntry]`, `updated_at`
  - `MetricsPackEntry`: `kind: str`, `enabled: bool`, `threshold: float | None`, `config: dict`, `evaluator_id: UUID | None`, `removable: bool`
- Default factory:

```python
DEFAULT_RAG_ENTRIES = (
    MetricsPackEntry(kind="hit_at_k", enabled=True, threshold=0.8, config={"k": 5}, removable=False),
    MetricsPackEntry(kind="groundedness", enabled=True, threshold=0.7, config={}, removable=False),
    MetricsPackEntry(kind="correctness", enabled=True, threshold=0.7, config={}, removable=False),
    MetricsPackEntry(kind="latency", enabled=True, threshold=None, config={"max_ms": 5000}, removable=False),
)
```

- Rules: cannot remove entry with `removable=False`; can set `enabled=False`; can patch threshold/config; can append custom entries with `removable=True`.

- Table `metrics_packs`: `id UUID PK`, `project_id UUID UNIQUE NOT NULL REFERENCES projects`, `entries JSONB NOT NULL`, `updated_at timestamptz`.

- [ ] **Step 1: Domain tests for create/patch/remove rules**

- [ ] **Step 2: Implement domain + migration + SQL repo**

- [ ] **Step 3: Tests PASS** (`alembic upgrade head` in CI/local)

- [ ] **Step 4: Ready to commit** (`feat: add metrics pack domain and table`)

---

### Task 7: Metrics pack application + API + ensure on first `rag_qa` dataset

**Files:**
- Create: `backend/src/aiobs/application/metrics_packs.py`
- Create: `backend/src/aiobs/api/routes/metrics_packs.py`
- Modify: `backend/src/aiobs/api/routes/__init__.py`, `deps.py`, `schemas.py`
- Modify: `backend/src/aiobs/application/datasets.py` — after creating `task_type=rag_qa` dataset, call `EnsureMetricsPack`
- Test: `backend/tests/test_api_metrics_packs.py`

**Interfaces:**
- `EnsureMetricsPack(project_id)` → creates pack with defaults if missing; for each default kind, ensure an `Evaluator` row exists in the project (`name` = kind, `config.kind` = kind, type deterministic/llm_judge) and store `evaluator_id` on entry.
- `GetMetricsPack(project_id)`
- `PatchMetricsPack(project_id, entries_patch)` — apply enable/threshold/config; add custom by `kind` + optional existing `evaluator_id`
- Routes:
  - `GET /api/v1/projects/{project_id}/metrics-pack`
  - `PUT /api/v1/projects/{project_id}/metrics-pack` (full replace of mutable fields; reject deleting non-removable kinds)
  - `POST /api/v1/projects/{project_id}/metrics-pack/ensure` (idempotent)

- [ ] **Step 1: API tests** — ensure creates 4 entries with evaluator_ids; cannot drop `hit_at_k`; can disable; creating rag_qa dataset auto-ensures

- [ ] **Step 2: Implement use cases + routes**

- [ ] **Step 3: Tests PASS**

- [ ] **Step 4: Ready to commit** (`feat: metrics pack API and auto-ensure for rag_qa`)

---

### Task 8: Score run from metrics pack

**Files:**
- Modify: `backend/src/aiobs/application/evaluate.py` (or new `ScoreExperimentFromPack`)
- Modify: `backend/src/aiobs/api/routes/experiments.py` — `POST /api/v1/experiments/{id}/evaluate-pack`
- Modify: `backend/src/aiobs/application/compare.py` — reject different `dataset_id`
- Test: `backend/tests/test_api_evaluation.py`, `test_api_compare.py`

**Interfaces:**
- `ScoreExperimentFromPack`: load pack for experiment.project_id; take enabled entries with `evaluator_id`; call existing `EvaluateExperiment` with those ids; set experiment status `completed` when done.
- Before scoring, optionally set status `running`.
- Compare: if `experiment.dataset_id != baseline.dataset_id` → `InvalidCompareSelectionError` / HTTP 400 with message `Runs must share the same dataset (test set version)`.

- [ ] **Step 1: Failing tests** for evaluate-pack uses pack evaluators; compare mismatch 400

- [ ] **Step 2: Implement**

- [ ] **Step 3: Tests PASS**

- [ ] **Step 4: Ready to commit** (`feat: evaluate experiment from project metrics pack`)

---

### Task 9: SDK bind helpers + retrieval documents attribute

**Files:**
- Create: `sdk/src/aiobs/_eval_run.py`
- Modify: `sdk/src/aiobs/_trace.py` and/or export from `__init__.py`
- Test: `sdk/tests/test_eval_bind.py`

**Interfaces:**
- Produces:

```python
def bind_evaluation(*, experiment_id: str, dataset_item_id: str) -> None:
    set_attributes({
        "aiobs.experiment_id": experiment_id,
        "aiobs.dataset_item_id": dataset_item_id,
    })

def set_retrieval_documents(documents: list[dict[str, object]]) -> None:
    # validates each has id; sets retrieval.documents + retrieval.document_count
    set_attributes({
        "retrieval.document_count": len(documents),
        "retrieval.documents": documents,
    })
```

- [ ] **Step 1: Failing SDK tests** with mocked span / existing otel test patterns in `sdk/tests/test_trace.py`

- [ ] **Step 2: Implement + export in `__all__`**

- [ ] **Step 3: Tests PASS**

- [ ] **Step 4: Ready to commit** (`feat(sdk): bind_evaluation and set_retrieval_documents`)

---

### Task 10: OTLP ingest binds run outputs

**Files:**
- Create: `backend/src/aiobs/tracing/run_binding.py`
- Modify: `backend/src/aiobs/api/routes/otlp.py` (after persist traces, attempt bind upsert)
- Modify: `backend/src/aiobs/api/deps.py`
- Test: `backend/tests/test_api_otlp_run_binding.py`

**Interfaces:**
- `extract_run_binding(trace: Trace) -> tuple[UUID, UUID] | None` from root/chain span attrs
- `build_output_from_trace(trace) -> {actual_output, context, metadata}`:
  - `actual_output` = trace.output
  - `context.documents` from retrieval extraction
  - `context` latency from existing helper
  - `metadata["source_trace_id"] = trace.trace_id`
- If experiment id unknown or item not in experiment dataset → **ignore** (no 500); still store the trace.
- Upsert via `ExperimentItemOutputRepository`

- [ ] **Step 1: Failing integration test** — create project, rag dataset+item, experiment, send OTLP JSON with bind attrs + output + retrieval.documents → GET outputs shows actual_output + documents

- [ ] **Step 2: Implement hook in OTLP route after successful persist**

- [ ] **Step 3: Tests PASS**

- [ ] **Step 4: Ready to commit** (`feat: bind OTLP traces to experiment item outputs`)

---

### Task 11: FE navigation + Overview checklist (dataset-first)

**Files:**
- Modify: `frontend/components/quality-loop-strip.tsx`
- Modify: `frontend/components/app-shell.tsx`
- Modify: `frontend/features/overview/overview-dashboard.tsx`
- Modify: `frontend/features/overview/loop-progress.tsx`
- Modify: copy in dataset/experiment list pages (“Test set”, “Runs”)
- Create: `frontend/app/(app)/metrics/page.tsx` (shell linking to pack UI — can stub until Task 12)
- Test: `cd frontend && npm run typecheck`

**Interfaces:**
- Loop steps: `Test set (/datasets)` → `Metriche (/metrics)` → `Runs (/experiments)` → `Confronta` → `Release`
- Remove Traces from strip (keep `/traces` in app shell under secondary/footer or omit from primary nav — **omit from primary NAV**; keep route working for item deep links)
- Overview cards: Test set / Metriche / Runs / Release readiness

- [ ] **Step 1: Update strip + shell labels/hrefs**

- [ ] **Step 2: Update Overview card model**

- [ ] **Step 3: typecheck PASS**

- [ ] **Step 4: Ready to commit** (`feat(web): dataset-first nav and overview checklist`)

---

### Task 12: FE Test set import + Metriche pack page

**Files:**
- Create: `frontend/features/datasets/import-dataset-dialog.tsx`
- Modify: `frontend/features/datasets/dataset-detail.tsx`, `dataset-list.tsx`
- Create: `frontend/lib/api/metrics-packs.ts`
- Create: `frontend/features/metrics/metrics-pack-page.tsx`, `use-metrics-pack.ts`
- Modify: `frontend/app/(app)/metrics/page.tsx`
- Modify: `frontend/lib/api/datasets.ts` — `importDatasetItems(datasetId, file)`
- Hide promote CTA: `frontend/features/traces/add-to-dataset-dialog.tsx` — remove trigger from trace detail **or** leave dialog unused (prefer remove button from `trace-detail-view.tsx`)

- [ ] **Step 1: API client + import dialog** (file input → multipart POST)

- [ ] **Step 2: Metrics page** — list pack entries, toggle enabled, edit threshold, show kind; “Ensure pack” button if 404

- [ ] **Step 3: typecheck PASS**

- [ ] **Step 4: Ready to commit** (`feat(web): test set import and metrics pack UI`)

---

### Task 13: FE Run detail — score pack + item timeline

**Files:**
- Modify: `frontend/features/experiments/experiment-detail.tsx`
- Create: `frontend/features/experiments/run-item-timeline.tsx`
- Modify: `frontend/lib/api/experiments.ts` — `evaluatePack(experimentId)`, fetch trace by `metadata.source_trace_id`
- Modify: compare view copy (“Runs must share same test set”)

**Interfaces:**
- Button **Score with metrics pack** → `POST …/evaluate-pack`
- Item panel shows: question, expected_answer, expected_doc_ids, retrieved documents, actual_output, scores
- Timeline: if `source_trace_id` present, load trace and reuse waterfall/sidebar components in compact form

- [ ] **Step 1: Wire evaluate-pack + empty states**

- [ ] **Step 2: Item detail + timeline component**

- [ ] **Step 3: typecheck PASS**

- [ ] **Step 4: Ready to commit** (`feat(web): run scoring and per-item timeline`)

---

### Task 14: Portfolio demo + docs

**Files:**
- Modify: `examples/hr_it_assistant/main.py` — `bind_evaluation`, full document payloads in `set_retrieval_documents`
- Modify: `examples/hr_it_assistant/kb.py` / `knowledge.json` — gold includes stable doc `id`; expected_answer strings
- Modify: `scripts/portfolio_demo.py` — create rag_qa items with `expected_doc_ids`; ensure metrics pack; evaluate-pack; release YAML uses pack metric names
- Modify: `docs/00-project-overview.md`, `02-domain-model.md`, `03-evaluation-engine.md`, `05-api.md`, `07-frontend.md`
- Modify: `README.md` — dataset-first quick story

- [ ] **Step 1: Update example app to bind run+item and emit document text**

- [ ] **Step 2: Update portfolio_demo flow** (dataset from items or from-trace still ok for bootstrap, but metadata must include `expected_doc_ids`; prefer creating items explicitly with gold)

- [ ] **Step 3: Doc edits aligned to spec**

- [ ] **Step 4: Manual smoke**

```bash
docker compose up --build
# ensure Ollama models; then
python scripts/portfolio_demo.py
```

Expected: pack metrics run; UI path Test set → Metriche → Runs works.

- [ ] **Step 5: Ready to commit** (`docs+demo: rag dataset-first portfolio path`)

---

## Spec coverage checklist

| Spec requirement | Task(s) |
|------------------|---------|
| Dataset-first FE flow | 11, 12 |
| Required question / expected_answer / expected_doc_ids | 1, 2, 3 |
| CSV/JSON import | 3, 12 |
| Project metrics pack defaults + custom | 6, 7, 12 |
| hit@k | 4 |
| Groundedness uses retrieved chunks | 5, 10 |
| Run = experiment; SDK bind run_id+item_id | 9, 10 |
| Per-item timeline under run | 13 |
| Compare same test set version | 8 |
| No production promote in vertical | 12 (hide CTA) |
| Portfolio uses RAG pack | 14 |
| No embedded RAG engine | (non-goal; no task) |

## Self-review notes

- Locked CSV columns and metadata key names (spec open questions).
- Pack persistence = dedicated `metrics_packs` table (spec open question).
- `answer_relevance` not in default pack (optional custom only).
- Placeholder scan: none intentionally left.
- Type names consistent: `hit_at_k`, `EXPECTED_DOC_IDS_KEY`, `bind_evaluation`, `evaluate-pack`.
