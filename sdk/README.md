# opengrade

Python SDK for the AI Evaluation & Observability Platform: OTLP/HTTP export with optional OpenInference instrumentation, plus a control-plane `Client` for datasets, experiments, and evaluation.

## Install

```bash
pip install opengrade-ai
pip install 'opengrade-ai[openai]'
pip install 'opengrade-ai[ai]'   # all tier-1 OpenInference instrumentors
pip install 'opengrade-ai[ui]'  # also installs opengrade-ai-server (API + packaged UI)
```

Individual extras: `openai`, `anthropic`, `langchain`, `llama-index`, `bedrock`, `ui`.

Import path remains `import opengrade`. Local platform (SQLite + UI):

```bash
pip install 'opengrade-ai[ui]'
opengrade ui   # http://127.0.0.1:8000 — creates ./opengrade.db
```

The `opengrade` command ships with the SDK. Without the `[ui]` extra it exits with a hint to install it.

Develop from this monorepo:

```bash
cd sdk && uv sync --extra dev
uv sync --extra openai   # add OpenAI instrumentor
# UI packaging (server wheel): ./scripts/package-ui.sh then cd backend && uv sync
```

## Quickstart

One tracking URI, one active project, one `init`. A `@trace` wrapper for your app logic, and provider calls become child spans when the matching instrumentor is installed:

```python
import opengrade
from openai import OpenAI

opengrade.set_tracking_uri("http://localhost:8000")  # or OPENGRADE_TRACKING_URI
opengrade.set_project("demo")  # created if it does not exist
opengrade.init(instrument="auto")  # OTLP → <tracking_uri>/v1/traces

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


@opengrade.trace
def ask(q: str) -> str:
    r = client.chat.completions.create(
        model="gemma4:e2b",
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


ask("ping")
opengrade.flush()
```

Runnable example: [`examples/sdk_hello/`](../examples/sdk_hello/README.md) (Ollama via OpenAI-compatible API).

### API summary

| Function | Purpose |
|---|---|
| `opengrade.set_tracking_uri(uri)` | Platform URL for both `Client` and OTLP (`<uri>/v1/traces`) |
| `opengrade.set_project(name)` | Get-or-create project by slug/name; becomes the default for `init()` |
| `opengrade.aset_project(name)` | Async variant of `set_project` (uses shared `AsyncClient`) |
| `opengrade.get_client()` | Shared `Client` bound to the tracking URI (no per-call `Client()`) |
| `opengrade.get_async_client()` | Shared `AsyncClient` for async app code |
| `opengrade.get_project()` | Project set via `set_project` / `aset_project`, or `None` |
| `opengrade.init(...)` | OTLP exporter, project headers, optional `instrument="auto"` \| list \| `False` |
| `@opengrade.trace` / `@opengrade.trace_async` | Parent CHAIN span; optional input/output capture (32 KiB cap) |
| `opengrade.set_input` / `set_output` | Override OpenInference I/O on the current span (no OTEL import) |
| `opengrade.set_attribute` / `set_attributes` | Custom attributes on the current span |
| `opengrade.set_error(...)` | Mark current span ERROR |
| `opengrade.current_trace_id()` | 32-char hex trace id while inside a `@trace` span |
| `opengrade.bind_evaluation(...)` | Bind current span to `experiment_id` + `dataset_item_id` |
| `opengrade.set_retrieval_documents([...])` | Attach retrieval docs for RAG eval context |
| `opengrade.flush()` | Drain the batch span processor before exit |
| `opengrade.evaluate(...)` | Run a task over a dataset, score, compare with a baseline → `ExperimentResult` |
| `opengrade.start_experiment(...)` | Context manager for a manual item loop (`exp.items()`, `exp.run(item)`) |
| `opengrade.Client(...)` | Control-plane REST client (projects, datasets, experiments, …) |
| `opengrade.AsyncClient(...)` | Async control-plane client (projects, live_runs, trace_scores, health) |

App code should use these helpers instead of importing OpenTelemetry directly.

## Experiments (`evaluate` / `start_experiment`)

One call runs a task over a dataset, writes the outputs, scores them and compares against a baseline:

```python
import opengrade

opengrade.set_project("demo")
opengrade.init()  # optional: adds trace context (tokens, cost, tool calls) to each item


def answer_question(item):  # item.input, item.expected_output, item.metadata
    docs = retrieve(item.input)
    opengrade.set_retrieval_documents(docs)  # feeds hit_at_k / recall_at_k / groundedness
    return generate(item.input, docs)


def short(item, output) -> bool:  # local metric: float | bool | None
    return len(output) < 400


result = opengrade.evaluate(
    dataset="gold-v1",  # name/id, path, list/iterable of dicts, pandas/Polars DataFrame
    task=answer_question,
    metrics=["groundedness", "hit_at_k", short],
    name="gemma-prompt-v2",
    params={"model": "gemma4"},  # stored as the experiment's model_config
    baseline="prod",  # experiment name (latest) or id
    max_concurrency=8,
)
print(result.summary(), result.url)
```

Manual loop, same plumbing (binding, flush, output upload, scoring on exit):

```python
with opengrade.start_experiment("v2", dataset="gold-v1", metrics=["hit_at_k"]) as exp:
    for item in exp.items():
        with exp.run(item) as run:  # root span bound to (experiment, item)
            run.log(my_app(item.input))  # or opengrade.set_output(...) anywhere inside
print(exp.result.summary())
```

How it behaves:

- **Metrics**: a string is a server metric kind (`hit_at_k`, `recall_at_k`, `mrr`, `must_contain`, `groundedness`, `correctness`, `answer_relevance`, `context_precision`, `context_recall`, `latency`). A dict sets threshold/config, for example `{"kind": "hit_at_k", "config": {"k": 3}}`. The SDK finds or creates a metrics set that holds exactly those kinds, using the project's defaults for anything you leave out. `metrics=None` uses the project default set. A Python metric runs locally (see *Custom metrics* below), and its scores are submitted to the platform (`POST /experiments/{id}/client-results`). From there they are aggregated, shown in the UI and compared with the baseline like server metrics.
- **Datasets**: pass a registered name/id, a path to CSV/JSON/JSONL, a list or iterable of dicts, a pandas DataFrame, or a Polars DataFrame. Rows need an `input` column (or `question`). `expected_output` (or `expected_answer`), `context` and `metadata` map to item fields; any other column goes into `metadata` (so `expected_doc_ids` and `must_contain` work). A missing `input`/`question` raises `opengrade.DatasetColumnError` (CSV headers are checked up front). Inline rows are hashed into a dataset name, so re-running on the same rows reuses the same dataset. Generators are materialised before upload (no lazy streaming).
- **Outputs** are uploaded with `PUT /experiments/{id}/outputs`, so this works without `opengrade.init()`. With tracing on, `finish()` waits for the OTLP traces to be bound (up to 30s) and merges their context in. Your explicit output always wins.
- **Errors**: when a task raises, `evaluate` records it on the item (`result.errors`, `metadata.error`) and moves on. Pass `raise_on_error=True` to stop instead. When the `with` block raises, nothing is scored. Bad dataset columns raise `DatasetColumnError` before the run starts.

### Custom metrics

```python
@opengrade.metric(threshold=0.5, version=2, requires=("documents",))
def cites_source(s: opengrade.Sample) -> opengrade.Score:
    hit = any(d["id"] in s.output for d in s.documents)
    return opengrade.Score(1.0 if hit else 0.0, explanation="cited" if hit else "no citation")


opengrade.evaluate(dataset="gold-v1", task=answer_question, metrics=["hit_at_k", cites_source])
```

- `Sample` fields: `input`, `output`, `expected` (dataset `expected_output`), `documents` (from `set_retrieval_documents`), `context`, `metadata`, `trace_id`, `item_id`.
- Return `opengrade.Score(value, label=, explanation=, metadata=)`, a float, a bool, `None` or `{"score": ...}`. The explanation shows per item in the UI; `metadata` (JSON-serializable, no NaN/inf) is stored with the result. A non-finite score is an ERROR.
- `label` can only fail, skip or error an item (`"FAIL"`, `"SKIPPED"`, `"ERROR"`): PASS/FAIL otherwise comes from the threshold, so `label="PASS"` does not make a score below the threshold pass.
- To change the threshold or name of an existing metric, wrap it again: `opengrade.LocalMetric(cites_source, threshold=0.8)` keeps its function, `requires` and config.
- `fn(item, output)` (two parameters) still works and receives the dataset item. `async def` metrics work too.
- `requires`: `Sample` fields that must be non-empty (`output`, `expected`, `documents`, `context`). When one is missing the item is SKIPPED, not failed.
- `version` is stored in the metric config: bump it when the code changes, so compare reports a config mismatch instead of a misleading delta.
- When the task fails on an item, that item counts as FAIL (score 0). When the metric raises, the item is ERROR. A local metric name must not match a server evaluator name (409). If the submission fails, `result.metrics` falls back to the in-process mean.

### Params and run metrics
```python
with opengrade.start_experiment("v2", dataset="gold-v1", params={"model": "gemma4"}) as exp:
    exp.log_params(temperature=0.2)  # merged into the experiment's model_config
    exp.run_task(answer_question)
    opengrade.log_metrics({"cost_usd": total_cost})  # experiment-level scalar, last value wins
print(exp.result.experiment_metrics)
```

- `log_params` merges into `model_config` until an evaluation starts. After that, or when the experiment was created from an app config, the server answers 409: start a new experiment instead.
- `log_metrics` stores one final number per key (no steps). Keys use letters, digits and `_ . - /`. They appear in `result.summary()` with the delta against the baseline, and can gate a release via the release-check policy: `{"experiment_metrics": {"cost_usd": {"max": 2.0}}}`.
- `opengrade.log_params` / `opengrade.log_metrics` act on the active experiment: inside `with start_experiment(...)` and inside any item run (`exp.run(...)`, `run_task`, `evaluate()` tasks). Elsewhere they raise `RuntimeError`. With concurrency > 1, call `log_metrics`/`log_params` once outside per-item code: per-item calls overwrite each other (last write wins).
- Every `finish()` logs `opengrade.error_rate`, `opengrade.latency_p50_ms` and `opengrade.latency_p95_ms` (the task's wall-clock latency as measured by the SDK, over the items that did not fail, nearest-rank percentiles).

## Control plane (`Client`)

HTTP client for the platform JSON API (uses `httpx2`, a core SDK dependency). Without `base_url` it uses the tracking URI. In app code prefer the shared instance, `opengrade.get_client()`, over building a `Client()` per function:

```python
import opengrade

opengrade.set_project("demo")
client = opengrade.get_client()
datasets = client.datasets.list()  # project_id defaults to the active project
exp = client.experiments.create(name="baseline", dataset_id=datasets[0].id)
```

Project-scoped methods (`datasets.create/list/create_with_items`, `experiments.create/list`, `metrics_packs.ensure/get`, `live_runs.submit/list`, `projects.get`) take `project_id` as an optional first argument: explicit value > `set_project()` > `OPENGRADE_PROJECT_ID`, else `ValueError`.

Explicit, self-managed client:

```python
from opengrade import Client

with Client("http://localhost:8000") as client:
    project = client.projects.create(name="Demo", slug="demo")
    ds = client.datasets.create_with_items(
        project.id,
        name="gold-v1",
        task_type="rag_qa",
        items=[{"input": "Q?", "expected_output": "A"}],
    )
    # or CSV/JSONL via multipart import:
    # client.datasets.import_items(ds.id, path="gold.csv", format="csv")

    exp = client.experiments.create(
        project.id,
        name="baseline",
        dataset_id=ds.id,
        model_config={"model": "gemma4:e2b"},
    )
    client.metrics_packs.ensure(project.id)
    # after OTLP-bound runs:
    client.experiments.evaluate_pack(exp.id)
    summary = client.experiments.summary(exp.id)
```

Control-plane methods return **Pydantic** models (see `opengrade.models`); use attributes or `.model_dump()` for a dict. Prefer `with Client(...)` / `client.close()` so the shared `httpx2` connection pool is released.

Namespaces: `projects`, `datasets` (`create`, `create_with_items`, `add_item`, `get`, `list`, `import_items`), `experiments` (`create`, `get`, `list_outputs`, `upsert_outputs`, `evaluate_pack`, `summary`, `compare`), `metrics_packs` (`ensure`, `get`), `metrics_sets` (`list`, `get`, `create`), `live_runs` (`submit`, `list`, `get`, `promote`, `rescore`), `app_configs` (same methods as `AppConfigClient`). Non-2xx responses raise `OpengradeAPIError` (with parsed FastAPI `detail` when present).

### Async control plane (`AsyncClient`)

For FastAPI / async RAG apps, use `AsyncClient` so control-plane calls do not block the event loop. Prefer `opengrade.get_async_client()` and `await opengrade.aset_project(...)`. MVP surface: `health`, `projects`, `live_runs` (full), `trace_scores`. Datasets, experiments, metrics packs/sets, and app configs remain on the sync `Client`.

```python
import opengrade


# FastAPI lifespan
async def lifespan(app):
    opengrade.set_tracking_uri("http://localhost:8000")
    await opengrade.aset_project("my-rag")
    opengrade.init(instrument=False)
    yield
    await opengrade.get_async_client().aclose()


@opengrade.trace_async(name="answer")
async def answer(q: str) -> str:
    text = "..."
    client = opengrade.get_async_client()
    await client.live_runs.submit(question=q, answer=text, documents=[])
    return text
```

Or manage the client yourself: `async with AsyncClient(...) as client: ...`. Changing `set_tracking_uri` resets both shared clients; if an event loop is already running, `aclose` the async client before changing the URI (otherwise the shared async client is dropped with a warning).

### Live runs from tracing (production)

With `live=True`, the outermost `@opengrade.trace` call outside an experiment becomes a live interaction at OTLP ingestion; no separate `live_runs.submit` call is needed.

```python
opengrade.init(
    project_slug="acme", live=True, live_sample_rate=0.1
)  # or OPENGRADE_LIVE=1, OPENGRADE_LIVE_SAMPLE_RATE=0.1


@opengrade.trace
def answer(question: str) -> str:
    docs = retrieve(question)  # documents from RETRIEVER spans or set_retrieval_documents()
    return llm(question, docs)
```

- Every call is recorded; only `live_sample_rate` of them (default `1.0`) are sent to the judge. The rest show `judge_status="unsampled"` and can still be judged with `live_runs.rescore`. Sampling is deterministic on the trace id.
- Question = the only string argument (or a `question`/`query`/`input`/`prompt` kwarg); answer = the return value. Override with `opengrade.set_input(...)` / `opengrade.set_output(...)`.
- `@opengrade.trace(live=False)` excludes a function; `live=True` opts one in when `init(live=...)` is off.
- The server must run with `CONTENT_CAPTURE_ENABLED=true`, otherwise input/output are redacted and no live interaction is created.
- Idempotent per trace (`external_id="trace:<trace_id>"`).

### Production scores and feedback

Attach scores and end-user feedback to a production trace. They are stored per trace and show up on the Live page (next to the judge verdicts), in the "Failing" filter and on the overview.

```python
opengrade.init(live=True)


@opengrade.metric(threshold=0.5, requires=("documents",))
def cites_source(s: opengrade.Sample) -> float:
    return float(any(d["id"] in s.output for d in s.documents))


@opengrade.trace(
    metrics=[cites_source], metrics_sample_rate=0.2
)  # 20% of traces, scored off the request path
def answer(question: str) -> str:
    docs = retrieve(question)
    opengrade.set_retrieval_documents(docs)
    return generate(question, docs)


@opengrade.trace
def handle(question: str) -> dict:
    out = answer(question)
    opengrade.log_score("answer_chars", len(out))  # current trace
    return {"answer": out, "trace_id": opengrade.current_trace_id()}  # send the id to your frontend


# later, from the thumbs button (trace_id is the one handle() returned)
opengrade.log_feedback(True, trace_id=trace_id, user_id="user-42", comment="great")
```

- `log_score(name, value, *, trace_id=None, label=None, explanation=None, threshold=None, metadata=None)`: without `trace_id` it uses the current trace. PASS/FAIL follows the same rule as experiment metrics: a `FAIL` label fails; a value under `threshold` fails; otherwise, with a threshold a value at or above it passes, and without one only a value of 0 fails.
- `log_feedback(positive, *, trace_id=None, comment=None, user_id=None)`: stored as `user_feedback` (1 or 0); `positive` must be a bool (or 0/1). One value per user per trace: a user changing their mind replaces it. Without `user_id` the feedback is anonymous and all anonymous feedback on a trace shares one row (last write wins). A thumbs-down counts as a failure in the Live "Failing" filter.
- `opengrade.score_trace(metric, sample, trace_id=...)` runs one metric now, on the calling thread (only the sending is in the background), and stores the result. The trace is `trace_id`, else `sample.trace_id`, else the current trace. A raising metric queues `label="ERROR"` with the exception as explanation (returns `True` when that score is queued); missing `requires` skips with `False`.
- `@opengrade.trace(metrics=[...], metrics_sample_rate=1.0)` runs your metrics after the function returns successfully (not when it raises, not inside experiments, which score their own metrics). Needs `opengrade.init()`. Sampling is per trace and configured separately from the judge's `live_sample_rate`; both use the same hash of the trace id, so when both are set the sampled traces are nested (the lower rate's traces are a subset of the higher rate's).
  - `Sample.input` is what you passed to `opengrade.set_input()` inside the call, else the only argument, else `{"args", "kwargs"}`; `Sample.documents` is the last `set_retrieval_documents()` inside the call (including nested `@opengrade.trace` helpers on the same thread); `expected` is `None`, so metrics with `requires=("expected",)` are skipped. Input, output and documents are deep-copied when the job is queued (so later mutation is invisible); samples over 256 KiB serialized are skipped with a warning. Capture uses a ContextVar: a worker thread your function starts does not inherit it, so `set_retrieval_documents` (or `record_documents`) from that thread does not feed the outer sample — call it on the traced thread before return, or pass documents into the metric yourself.
  - Metrics run on a background pool (default 2 threads; `init(metrics_workers=...)` or `OPENGRADE_METRICS_WORKERS`) fed by a bounded queue; when it is full the call is not scored and a warning is logged. Async metrics time out after 60 s; a sync metric cannot be interrupted. A raising or timed-out metric stores `label="ERROR"` with the exception as explanation (never breaks the traced call). For LLM judges raise `metrics_workers` or lower `metrics_sample_rate`.
  - Metrics run with instrumentation suppressed: LLM calls a judge makes and `@opengrade.trace` helpers it calls do not create production traces (spans started manually with an OpenTelemetry tracer still do).
  - `trace(metrics=...)` rejects async and generator functions; use `trace_async` for coroutines.
    `trace_async` also accepts `functools.partial` of a coroutine function; other async wrappers
    need `inspect.markcoroutinefunction`.
- These calls never raise. `log_score`, `log_feedback` and `trace(metrics=...)` never block the caller; `score_trace()` blocks for as long as the metric takes. Invalid input (bad value, label or trace id, or metadata over 16 KB serialized) logs a warning and returns `False`; setup problems (no project id, no active trace) warn at most once a minute.
- Scores are sent in the background (batches every 2 s, 100 scores or about 512 KB). A 413 (body over the server's 1 MiB limit) splits the batch in half and resends, dropping only a single score that is still too large. A batch rejected with 400/422 is resent item by item so only the bad scores are dropped; 401/403/404 and other 4xx drop the batch at once; only network errors and 5xx are retried once after a 1 s backoff, then dropped with a warning.
- `opengrade.flush(timeout_millis)` is one total budget: spans, then pending metrics, then scores. At exit, spans, pending metrics, and scores share one ~5 s budget (span flush is capped at ~2 s of that).

### Live runs → TestSet loop

```python
from opengrade import Client

with Client() as client:
    project_id = "..."  # existing project
    live = client.live_runs.submit(
        project_id,
        question="How many PTO days?",
        answer="Unlimited.",
        documents=[{"id": "pto", "text": "Full-time staff get 20 PTO days."}],
    )
    detail = client.live_runs.get(live.id)  # or list(..., failed_only=True)
    # After review, promote with reviewer-authored gold (never copy the prod answer):
    ds = client.datasets.create(project_id, name="from-live", task_type="rag_qa")
    client.live_runs.promote(
        live.id,
        dataset_id=ds.id,
        expected_output="Full-time employees get 20 PTO days per year.",
        expected_doc_ids=["pto"],
    )
    exp = client.experiments.create(project_id, name="after-promote", dataset_id=ds.id)
    client.experiments.evaluate_pack(exp.id)
```

See also [`scripts/live_run_demo.py`](../scripts/live_run_demo.py) (`--promote`).

Eval binding still uses tracing attributes (no REST call):

```python
@opengrade.trace
def run_item(question: str) -> str:
    opengrade.bind_evaluation(experiment_id=exp_id, dataset_item_id=item_id)
    ...
```

### Registry (app configs)

`AppConfigClient` remains available for standalone use; `client.app_configs` exposes the same API:

```python
from opengrade import AppConfigClient

registry = AppConfigClient("http://localhost:8000")
created = registry.create_app_config(
    project_id,
    "rag-faq",
    prompt={"system": "You are helpful."},
    model={"model_id": "demo"},
)
latest = registry.list_app_configs(project_id, latest=True)
registry.set_alias(project_id, "baseline", created.id)
```

Methods: `create_app_config`, `list_app_configs` (`name`, `latest`), `set_alias`, `get_aliases`.

End-to-end prompt A/B on the People Ops RAG example (same model, two App Config prompts): `python scripts/prompt_ab_demo.py` — see `examples/hr_it_assistant/README.md`.

## Tier-1 compatibility matrix

| Key | Target library | OpenInference package | Notes |
|---|---|---|---|
| `openai` | `openai` | `openinference-instrumentation-openai` | OpenAI API and OpenAI-compatible endpoints (e.g. Ollama `/v1`) |
| `anthropic` | `anthropic` | `openinference-instrumentation-anthropic` | Documented; manual smoke outside default CI |
| `langchain` | `langchain` / `langchain_core` | `openinference-instrumentation-langchain` | Documented; manual smoke outside default CI |
| `llama_index` | `llama_index` | `openinference-instrumentation-llama-index` | Extra name: `llama-index` |
| `bedrock` | `boto3` (Bedrock runtime) | `openinference-instrumentation-bedrock` | Documented; manual smoke outside default CI |

Install the extra for the providers you use, then `init(instrument="auto")` activates every tier-1 entry whose target library and instrumentor package are importable. Use `init(instrument=["openai", "langchain"])` to restrict keys, or `instrument=False` for decorator-only tracing.

## Environment variables

| Variable | Purpose |
|---|---|
| `OPENGRADE_TRACKING_URI` | Platform URL for `Client()` and OTLP (default `http://localhost:8000`); `set_tracking_uri()` wins |
| `OPENGRADE_PROJECT_ID` | Project UUID header (`X-Project-Id`); used when no `set_project()` / `init()` argument |
| `OPENGRADE_PROJECT_SLUG` | Project slug header (`X-Project-Slug`); the project must already exist |
| `OPENGRADE_SERVICE_NAME` | OpenTelemetry `service.name` (default `opengrade-app`) |
| `OPENGRADE_OTLP_ENDPOINT` | Optional override of the derived OTLP URL (e.g. a separate collector) |
| `OPENGRADE_DISABLED` | `1` / `true` / `yes` / `on` turns `init()` into a no-op (decorators keep working, nothing is exported) |
| `OPENGRADE_METRICS_WORKERS` | Size of the `@opengrade.trace(metrics=...)` background pool (default `2`, range 1–64); `init(metrics_workers=...)` wins |

Project precedence for `init()`: arguments > `set_project()` > env.

## Failure behavior

Tracing never breaks the host app:

- `init()` never raises. Without a project it logs a warning on the `opengrade` logger and stays a no-op; a broken instrumentor is skipped with a warning.
- Pending spans are flushed at interpreter exit (`atexit`, sharing the ~5 s exit budget with metrics/scores; span stage capped at ~2 s), so short scripts don't need `opengrade.flush()`.
- If the platform is unreachable, spans are dropped: one warning when export starts failing, one info when it recovers. After a failure, export pauses for 30s, so a platform that is down adds no network calls and doesn't slow down exit.

## Content capture

The SDK may set OpenInference `input` / `output` attributes on decorated spans (`capture_input` / `capture_output`, default on). The platform API applies its own policy: with `CONTENT_CAPTURE_ENABLED=false` (default), stored trace bodies may be redacted or omitted even if the SDK sent attributes. Configure both sides explicitly for demos that need bodies in the UI.

## Monorepo note

- SDK PyPI / import / CLI: `opengrade-ai` / `opengrade` / `opengrade`
- Server PyPI / import / CLI: `opengrade-ai-server` / `opengrade_server` / `opengrade-server` (share one venv via `opengrade-ai[ui]`)

## Manual smoke (not CI-required)

With the platform running and a project created:

**Anthropic**

```bash
cd sdk && uv sync --extra anthropic --extra dev
uv pip install anthropic
uv run python -c "
import opengrade
import anthropic
opengrade.init(project_slug='demo', instrument=['anthropic'])
c = anthropic.Anthropic()
@opengrade.trace
def go():
    c.messages.create(model='claude-3-5-haiku-20241022', max_tokens=16, messages=[{'role':'user','content':'hi'}])
go(); opengrade.flush()
"
```

**LangChain**

```bash
cd sdk && uv sync --extra langchain --extra dev
# install langchain + your LLM backend as needed
uv run python -c "
import opengrade
opengrade.init(project_slug='demo', instrument=['langchain'])
# invoke your LangChain chain here
opengrade.flush()
"
```

See platform tracing docs: [`docs/04-tracing-and-otel.md`](../docs/04-tracing-and-otel.md).
