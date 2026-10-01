# aiobs

Python SDK for the AI Evaluation & Observability Platform: OTLP/HTTP export with optional OpenInference instrumentation for popular AI libraries.

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
| `aiobs.flush()` | Drain the batch span processor before exit |

App code should use these helpers instead of importing OpenTelemetry directly.

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
