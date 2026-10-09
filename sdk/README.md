# aiobs

Python SDK for the AI Evaluation & Observability Platform: OTLP/HTTP export with optional OpenInference instrumentation, plus a control-plane `Client` for datasets, experiments, and evaluation.

## Install

```bash
pip install aiobs
pip install 'aiobs[openai]'
pip install 'aiobs[ai]'   # all tier-1 OpenInference instrumentors
```

Individual extras: `openai`, `anthropic`, `langchain`, `llama-index`, `bedrock`.

Develop from this monorepo:

```bash
cd sdk && uv sync --extra dev
uv sync --extra openai   # add OpenAI instrumentor
```

## Quickstart

One `init`, a `@trace` wrapper for your app logic, and provider calls become child spans when the matching instrumentor is installed:

```python
import aiobs
from openai import OpenAI

aiobs.init(project_slug="demo", instrument="auto")

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
| `aiobs.init(...)` | OTLP exporter, project headers, optional `instrument="auto"` \| list \| `False` |
| `@aiobs.trace` / `@aiobs.trace_async` | Parent CHAIN span; optional input/output capture (32 KiB cap) |
| `aiobs.set_input` / `set_output` | Override OpenInference I/O on the current span (no OTEL import) |
| `aiobs.set_attribute` / `set_attributes` | Custom attributes on the current span |
| `aiobs.set_error(...)` | Mark current span ERROR |
| `aiobs.current_trace_id()` | 32-char hex trace id while inside a `@trace` span |
| `aiobs.bind_evaluation(...)` | Bind current span to `experiment_id` + `dataset_item_id` |
| `aiobs.set_retrieval_documents([...])` | Attach retrieval docs for RAG eval context |
| `aiobs.flush()` | Drain the batch span processor before exit |
| `aiobs.Client(...)` | Control-plane REST client (projects, datasets, experiments, …) |

App code should use these helpers instead of importing OpenTelemetry directly.

## Control plane (`Client`)

HTTP client for the platform JSON API (uses `httpx2`, a core SDK dependency). Point `base_url` at the FastAPI host (default `http://localhost:8000`, or `AIOBS_API_BASE_URL` / `AIOBS_BASE_URL`):

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

Namespaces: `projects`, `datasets` (`create`, `create_with_items`, `add_item`, `get`, `list`, `import_items`), `experiments` (`create`, `get`, `list_outputs`, `evaluate_pack`, `summary`, `compare`), `metrics_packs` (`ensure`, `get`), `app_configs` (same methods as `AppConfigClient`). Non-2xx responses raise `AiobsAPIError` (with parsed FastAPI `detail` when present).

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
| `AIOBS_PROJECT_ID` | Project UUID header (`X-Project-Id`); exactly one of id/slug required |
| `AIOBS_PROJECT_SLUG` | Project slug header (`X-Project-Slug`) |
| `AIOBS_OTLP_ENDPOINT` | OTLP/HTTP traces URL (default `http://localhost:8000/v1/traces`) |
| `AIOBS_SERVICE_NAME` | OpenTelemetry `service.name` (default `aiobs-app`) |
| `AIOBS_API_BASE_URL` | Default host for `Client()` (fallback: `AIOBS_BASE_URL`, then `http://localhost:8000`) |

Arguments to `init()` override these when set.

## Content capture

The SDK may set OpenInference `input` / `output` attributes on decorated spans (`capture_input` / `capture_output`, default on). The platform API applies its own policy: with `CONTENT_CAPTURE_ENABLED=false` (default), stored trace bodies may be redacted or omitted even if the SDK sent attributes. Configure both sides explicitly for demos that need bodies in the UI.

## Monorepo note

The FastAPI backend in `backend/` is also named `aiobs` on PyPI paths inside the repo. **Do not** `pip install` the SDK into the backend virtualenv (or vice versa)—use separate venvs (`sdk/.venv`, example dirs) to avoid import clashes.

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
