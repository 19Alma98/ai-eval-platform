# aiobs

Python SDK for the AI Evaluation & Observability Platform: OTLP/HTTP export with optional OpenInference instrumentation, plus a control-plane `Client` for datasets, experiments, and evaluation.

## Install

```bash
pip install aiobs-eval
pip install 'aiobs-eval[openai]'
pip install 'aiobs-eval[ai]'   # all tier-1 OpenInference instrumentors
pip install 'aiobs-eval[ui]'  # also installs aiobs-eval-server (API + packaged UI)
```

Individual extras: `openai`, `anthropic`, `langchain`, `llama-index`, `bedrock`, `ui`.

Import path remains `import aiobs`. Local platform (SQLite + UI):

```bash
pip install 'aiobs-eval[ui]'
aiobs ui   # http://127.0.0.1:8000 — creates ./aiobs.db
```

The `aiobs` command ships with the SDK. Without the `[ui]` extra it exits with a hint to install it.

Develop from this monorepo:

```bash
cd sdk && uv sync --extra dev
uv sync --extra openai   # add OpenAI instrumentor
# UI packaging (server wheel): ./scripts/package-ui.sh then cd backend && uv sync
```

## Quickstart

One tracking URI, one active project, one `init`. A `@trace` wrapper for your app logic, and provider calls become child spans when the matching instrumentor is installed:

```python
import aiobs
from openai import OpenAI

aiobs.set_tracking_uri("http://localhost:8000")  # or AIOBS_TRACKING_URI
aiobs.set_project("demo")                        # created if it does not exist
aiobs.init(instrument="auto")                    # OTLP → <tracking_uri>/v1/traces

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


@aiobs.trace
def ask(q: str) -> str:
    r = client.chat.completions.create(
        model="gemma4:e2b",
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


ask("ping")
aiobs.flush()
```

Runnable example: [`examples/sdk_hello/`](../examples/sdk_hello/README.md) (Ollama via OpenAI-compatible API).

### API summary

| Function | Purpose |
|---|---|
| `aiobs.set_tracking_uri(uri)` | Platform URL for both `Client` and OTLP (`<uri>/v1/traces`) |
| `aiobs.set_project(name)` | Get-or-create project by slug/name; becomes the default for `init()` |
| `aiobs.get_client()` | Shared `Client` bound to the tracking URI (no per-call `Client()`) |
| `aiobs.get_project()` | Project set via `set_project`, or `None` |
| `aiobs.init(...)` | OTLP exporter, project headers, optional `instrument="auto"` \| list \| `False` |
| `@aiobs.trace` / `@aiobs.trace_async` | Parent CHAIN span; optional input/output capture (32 KiB cap) |
| `aiobs.set_input` / `set_output` | Override OpenInference I/O on the current span (no OTEL import) |
| `aiobs.set_attribute` / `set_attributes` | Custom attributes on the current span |
| `aiobs.set_error(...)` | Mark current span ERROR |
| `aiobs.current_trace_id()` | 32-char hex trace id while inside a `@trace` span |
| `aiobs.bind_evaluation(...)` | Bind current span to `experiment_id` + `dataset_item_id` |
| `aiobs.set_retrieval_documents([...])` | Attach retrieval docs for RAG eval context |
| `aiobs.flush()` | Drain the batch span processor before exit |
| `aiobs.evaluate(...)` | Run a task over a dataset, score, compare with a baseline → `ExperimentResult` |
| `aiobs.start_experiment(...)` | Context manager for a manual item loop (`exp.items()`, `exp.run(item)`) |
| `aiobs.Client(...)` | Control-plane REST client (projects, datasets, experiments, …) |

App code should use these helpers instead of importing OpenTelemetry directly.

## Experiments (`evaluate` / `start_experiment`)

One call runs a task over a dataset, writes the outputs, scores them and compares against a baseline:

```python
import aiobs

aiobs.set_project("demo")
aiobs.init()  # optional: adds trace context (tokens, cost, tool calls) to each item


def answer_question(item):            # item.input, item.expected_output, item.metadata
    docs = retrieve(item.input)
    aiobs.set_retrieval_documents(docs)  # feeds hit_at_k / recall_at_k / groundedness
    return generate(item.input, docs)


def short(item, output) -> bool:       # local metric: float | bool | None
    return len(output) < 400


result = aiobs.evaluate(
    dataset="gold-v1",                 # name (latest version), id, list of dicts, DataFrame
    task=answer_question,
    metrics=["groundedness", "hit_at_k", short],
    name="gemma-prompt-v2",
    params={"model": "gemma4"},        # stored as the experiment's model_config
    baseline="prod",                   # experiment name (latest) or id
    max_concurrency=8,
)
print(result.summary(), result.url)
```

Manual loop, same plumbing (binding, flush, output upload, scoring on exit):

```python
with aiobs.start_experiment("v2", dataset="gold-v1", metrics=["hit_at_k"]) as exp:
    for item in exp.items():
        with exp.run(item) as run:   # root span bound to (experiment, item)
            run.log(my_app(item.input))  # or aiobs.set_output(...) anywhere inside
print(exp.result.summary())
```

How it behaves:

- **Metrics**: a string is a server metric kind (`hit_at_k`, `recall_at_k`, `mrr`, `must_contain`, `groundedness`, `correctness`, `answer_relevance`, `context_precision`, `context_recall`, `latency`). A dict sets threshold/config, for example `{"kind": "hit_at_k", "config": {"k": 3}}`. The SDK finds or creates a metrics set that holds exactly those kinds, using the project's defaults for anything you leave out. `metrics=None` uses the project default set. A Python metric runs locally (see *Custom metrics* below), and its scores are submitted to the platform (`POST /experiments/{id}/client-results`). From there they are aggregated, shown in the UI and compared with the baseline like server metrics. When the task fails on an item, that item counts as FAIL (score 0). When the metric itself raises, the item is recorded as ERROR. A local metric name must not match a server evaluator name (409). If the submission fails, `result.metrics` falls back to the in-process mean.
- **Datasets**: a list of dicts or a DataFrame needs an `input` column. `expected_output`, `context` and `metadata` map to item fields, and any other column goes into `metadata` (so `expected_doc_ids` and `must_contain` work). The dataset name is a hash of the rows, so re-running on the same rows reuses the same dataset.
- **Outputs** are uploaded with `PUT /experiments/{id}/outputs`, so this works without `aiobs.init()`. With tracing on, `finish()` waits for the OTLP traces to be bound (up to 30s) and merges their context in. Your explicit output always wins.
- **Errors**: when a task raises, `evaluate` records it on the item (`result.errors`, `metadata.error`) and moves on. Pass `raise_on_error=True` to stop instead. When the `with` block raises, nothing is scored.
- **Link**: `result.url` points to the experiment page on the tracking URI. Set `AIOBS_UI_URL` when the UI is served elsewhere (for example `http://localhost:3000` in the docker dev setup).

### Custom metrics

```python
@aiobs.metric(threshold=0.5, version=2, requires=("documents",))
def cites_source(s: aiobs.Sample) -> aiobs.Score:
    hit = any(d["id"] in s.output for d in s.documents)
    return aiobs.Score(1.0 if hit else 0.0, explanation="cited" if hit else "no citation")


aiobs.evaluate(dataset="gold-v1", task=answer_question, metrics=["hit_at_k", cites_source])
```

- `Sample` fields: `input`, `output`, `expected` (dataset `expected_output`), `documents` (from `set_retrieval_documents`), `context`, `metadata`, `trace_id`, `item_id`.
- Return `aiobs.Score(value, label=, explanation=, metadata=)`, a float, a bool, `None` or `{"score": ...}`. Explanation and metadata show up per item in the UI. A non-finite score is an ERROR.
- `fn(item, output)` (two parameters) still works and receives the dataset item. `async def` metrics work too.
- `requires`: `Sample` fields that must be non-empty (`output`, `expected`, `documents`, `context`). When one is missing the item is SKIPPED, not failed.
- `version` is stored in the metric config: bump it when the code changes, so compare reports a config mismatch instead of a misleading delta.
- When the task fails on an item, that item counts as FAIL (score 0). When the metric raises, the item is ERROR. A local metric name must not match a server evaluator name (409). If the submission fails, `result.metrics` falls back to the in-process mean.

### Ragas and DeepEval

```bash
pip install "aiobs-eval[ragas]"     # or "aiobs-eval[deepeval]"
```

```python
from aiobs.integrations.ragas import from_ragas
from aiobs.integrations.deepeval import from_deepeval
from ragas.metrics import Faithfulness
from deepeval.metrics import AnswerRelevancyMetric

metrics = [from_ragas(Faithfulness(llm=judge)), from_deepeval(AnswerRelevancyMetric())]
```

The adapters map `Sample` to `SingleTurnSample` / `LLMTestCase` (documents → retrieved/retrieval context), run the library's async scorer, and keep DeepEval's `reason` as the explanation. `requires` comes from the metric's required fields, so a metric that needs a reference is SKIPPED where there is none. Library version, metric class and judge model are stored in the config: upgrading Ragas or swapping the judge is reported as a config mismatch in compare.

- Only single-turn Ragas metrics are supported. DeepEval's lower-is-better metrics (`BiasMetric`, `ToxicityMetric`, `HallucinationMetric`, `PIILeakageMetric`) are rejected, because aiobs thresholds pass at or above the threshold: wrap them in your own `@aiobs.metric` instead.
- For `GEval`, pass explicit `evaluation_steps`: otherwise DeepEval generates new steps for every item, and scores are not comparable across items or runs.

## Control plane (`Client`)

HTTP client for the platform JSON API (uses `httpx2`, a core SDK dependency). Without `base_url` it uses the tracking URI. In app code prefer the shared instance, `aiobs.get_client()`, over building a `Client()` per function:

```python
import aiobs

aiobs.set_project("demo")
client = aiobs.get_client()
datasets = client.datasets.list()  # project_id defaults to the active project
exp = client.experiments.create(name="baseline", dataset_id=datasets[0].id)
```

Project-scoped methods (`datasets.create/list/create_with_items`, `experiments.create/list`, `metrics_packs.ensure/get`, `live_runs.submit/list`, `projects.get`) take `project_id` as an optional first argument: explicit value > `set_project()` > `AIOBS_PROJECT_ID`, else `ValueError`.

Explicit, self-managed client:

```python
from aiobs import Client

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

Control-plane methods return **Pydantic** models (see `aiobs.models`); use attributes or `.model_dump()` for a dict. Prefer `with Client(...)` / `client.close()` so the shared `httpx2` connection pool is released.

Namespaces: `projects`, `datasets` (`create`, `create_with_items`, `add_item`, `get`, `list`, `import_items`), `experiments` (`create`, `get`, `list_outputs`, `upsert_outputs`, `evaluate_pack`, `summary`, `compare`), `metrics_packs` (`ensure`, `get`), `metrics_sets` (`list`, `get`, `create`), `live_runs` (`submit`, `list`, `get`, `promote`, `rescore`), `app_configs` (same methods as `AppConfigClient`). Non-2xx responses raise `AiobsAPIError` (with parsed FastAPI `detail` when present).

### Live runs from tracing (production)

With `live=True`, the outermost `@aiobs.trace` call outside an experiment becomes a live interaction at OTLP ingestion; no separate `live_runs.submit` call is needed.

```python
aiobs.init(project_slug="acme", live=True, live_sample_rate=0.1)  # or AIOBS_LIVE=1, AIOBS_LIVE_SAMPLE_RATE=0.1

@aiobs.trace
def answer(question: str) -> str:
    docs = retrieve(question)            # documents from RETRIEVER spans or set_retrieval_documents()
    return llm(question, docs)
```

- Every call is recorded; only `live_sample_rate` of them (default `1.0`) are sent to the judge. The rest show `judge_status="unsampled"` and can still be judged with `live_runs.rescore`. Sampling is deterministic on the trace id.
- Question = the only string argument (or a `question`/`query`/`input`/`prompt` kwarg); answer = the return value. Override with `aiobs.set_input(...)` / `aiobs.set_output(...)`.
- `@aiobs.trace(live=False)` excludes a function; `live=True` opts one in when `init(live=...)` is off.
- The server must run with `CONTENT_CAPTURE_ENABLED=true`, otherwise input/output are redacted and no live interaction is created.
- Idempotent per trace (`external_id="trace:<trace_id>"`).

### Live runs → TestSet loop

```python
from aiobs import Client

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
@aiobs.trace
def run_item(question: str) -> str:
    aiobs.bind_evaluation(experiment_id=exp_id, dataset_item_id=item_id)
    ...
```

### Registry (app configs)

`AppConfigClient` remains available for standalone use; `client.app_configs` exposes the same API:

```python
from aiobs import AppConfigClient

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
| `AIOBS_TRACKING_URI` | Platform URL for `Client()` and OTLP (default `http://localhost:8000`); `set_tracking_uri()` wins |
| `AIOBS_PROJECT_ID` | Project UUID header (`X-Project-Id`); used when no `set_project()` / `init()` argument |
| `AIOBS_PROJECT_SLUG` | Project slug header (`X-Project-Slug`); the project must already exist |
| `AIOBS_SERVICE_NAME` | OpenTelemetry `service.name` (default `aiobs-app`) |
| `AIOBS_OTLP_ENDPOINT` | Optional override of the derived OTLP URL (e.g. a separate collector) |
| `AIOBS_DISABLED` | `1` / `true` / `yes` / `on` turns `init()` into a no-op (decorators keep working, nothing is exported) |

Project precedence for `init()`: arguments > `set_project()` > env.

## Failure behavior

Tracing never breaks the host app:

- `init()` never raises. Without a project it logs a warning on the `aiobs` logger and stays a no-op; a broken instrumentor is skipped with a warning.
- Pending spans are flushed at interpreter exit (`atexit`, max ~2s), so short scripts don't need `aiobs.flush()`.
- If the platform is unreachable, spans are dropped: one warning when export starts failing, one info when it recovers. After a failure, export pauses for 30s, so a platform that is down adds no network calls and doesn't slow down exit.

## Content capture

The SDK may set OpenInference `input` / `output` attributes on decorated spans (`capture_input` / `capture_output`, default on). The platform API applies its own policy: with `CONTENT_CAPTURE_ENABLED=false` (default), stored trace bodies may be redacted or omitted even if the SDK sent attributes. Configure both sides explicitly for demos that need bodies in the UI.

## Monorepo note

- SDK PyPI / import / CLI: `aiobs-eval` / `aiobs` / `aiobs`
- Server PyPI / import / CLI: `aiobs-eval-server` / `aiobs_server` / `aiobs-server` (share one venv via `aiobs-eval[ui]`)

## Manual smoke (not CI-required)

With the platform running and a project created:

**Anthropic**

```bash
cd sdk && uv sync --extra anthropic --extra dev
uv pip install anthropic
uv run python -c "
import aiobs
import anthropic
aiobs.init(project_slug='demo', instrument=['anthropic'])
c = anthropic.Anthropic()
@aiobs.trace
def go():
    c.messages.create(model='claude-3-5-haiku-20241022', max_tokens=16, messages=[{'role':'user','content':'hi'}])
go(); aiobs.flush()
"
```

**LangChain**

```bash
cd sdk && uv sync --extra langchain --extra dev
# install langchain + your LLM backend as needed
uv run python -c "
import aiobs
aiobs.init(project_slug='demo', instrument=['langchain'])
# invoke your LangChain chain here
aiobs.flush()
"
```

See platform tracing docs: [`docs/04-tracing-and-otel.md`](../docs/04-tracing-and-otel.md).
