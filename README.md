# OpenGrade

Self-hosted AI evaluation & observability — traces, datasets, experiments, CI gates.

[![CI](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/opengrade-ai)](https://pypi.org/project/opengrade-ai/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

OpenGrade is an open-source platform for AI quality engineering. Trace your app, turn
production traffic into test sets, run experiments, compare them with a baseline and fail CI when
quality drops. It runs on your machine or your servers: no hosted SaaS, traces and test sets stay on your
infrastructure (only the LLM judge calls go to the model provider you choose).

```text
 trace your app ──▶ build a test set ──▶ run an experiment ──▶ compare with the baseline ──▶ CI gate
       ▲                                                                                     │
       └────────────── production traces, scores and alerts ◀────────── ship ◀───────────────┘
```

![OpenGrade walkthrough: overview, traces, experiments, baseline compare, quality gate, production judge](docs/images/hero.gif)

## Is it a fit?

**Good fit:** AI features whose answers can be checked against something — RAG and Q&A
assistants, classification, structured extraction, tool calling with a fixed schema. You bring a
test set (or grow one from production), OpenGrade measures and gates.

**Not a fit:** open-ended agents where "good" is subjective, or a replacement for your APM. The
platform measures what you define; it does not invent a quality oracle. Details:
[project overview](docs/00-project-overview.md).

## How it works

| Piece | Install | Role |
|---|---|---|
| **SDK** `opengrade-ai` | `uv add opengrade-ai` | In your app and eval scripts: tracing, `evaluate` / `sweep`, custom metrics, production scores |
| **Server + UI** `opengrade-ai-server` | `uv add 'opengrade-ai[ui]'` or Docker Compose | Stores traces, datasets and experiments; runs the metrics and **LLM judges**; dashboard and REST API |
| **CLI** `opengrade` | ships with the SDK | `opengrade ui` (local server), `opengrade evaluate` / `check` (CI gate), `opengrade keys` |

The whole workflow — what runs where, how to build a test set, which metrics to pick, how
baselines move, how production feeds back into tests — is on one page:
**[How OpenGrade works →](docs/workflow.md)**

## Requirements

- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/) (pip works too).
- **Optional — an LLM for the judges** (`groundedness`, `correctness`, …): a local
  [Ollama](https://ollama.com) or any provider supported by [LiteLLM](https://docs.litellm.ai/docs/providers).
  Without one, tracing and the deterministic metrics (`hit_at_k`, `must_contain`, `latency`, …) still work.
- **Optional — Docker** for the PostgreSQL deployment. The local UI needs no Docker and no database server (SQLite).

## Quickstart

```bash
uv add 'opengrade-ai[ui]'
uv run opengrade ui   # http://127.0.0.1:8000, data in ./opengrade.db
```

With pip: `pip install 'opengrade-ai[ui]'`, then `opengrade ui`.

**[Get started in 15 minutes →](docs/getting-started.md)** — local UI, first trace, a scored experiment.

**[SDK tour →](examples/sdk_tour/README.md)** — runnable offline project: tracing, verifying a
RAG against a gold set, comparing architectures and models, custom metrics, alerts.

## What it looks like

**1. Trace your app.** A decorator for the whole request, a `with` block for each step. OpenAI,
Anthropic, LangChain, LlamaIndex and Bedrock calls become child spans automatically.

```python
import opengrade

opengrade.set_tracking_uri("http://localhost:8000")
opengrade.set_project("support-bot")
opengrade.init(instrument="auto")


@opengrade.trace
def answer(question: str) -> str:
    with opengrade.span("retrieve", kind="RETRIEVER", input=question) as s:
        docs = retriever.search(question)
        s.set_output([d.id for d in docs])
    opengrade.set_retrieval_documents(docs)  # feeds the retrieval metrics and RAG judges
    return llm.generate(question, docs)
```

**2. Evaluate it on a test set**, against a baseline:

```python
result = opengrade.evaluate(
    dataset="gold.jsonl",                   # or a dataset name, a list of dicts, a DataFrame
    task=lambda item: answer(item.input),
    metrics=["hit_at_k", "groundedness", "correctness", "latency"],
    baseline="alias:main",                  # the last run accepted on main
)
print(result.summary(), result.url)
```

**3. Gate the pull request.** A YAML policy, an exit code for CI:

```yaml
# opengrade.yaml
evaluate:
  task: rag_app:task
  dataset: gold.jsonl
  metrics: [hit_at_k, must_contain, latency]
  baseline: alias:main

hit_at_k: { min: 0.8 }
latency:  { p95_max_ms: 2000 }
regression:
  max_delta: -0.05                   # significant drop of the mean vs main → fail
  max_new_failures: 0                # a test case that passes on main must not fail
critical: { by: critical }           # must-pass test cases
```

```bash
opengrade evaluate --config opengrade.yaml --require-baseline   # exit 1 when the gate fails
```

**4. Watch production.** Score live traffic with the same metrics, collect user feedback, alert on drift:

```python
opengrade.init(live=True, live_sample_rate=0.1, version=GIT_SHA, environment="prod")
```

## Documentation

<!-- TODO: link the published docs site here once the Vercel URL is final. -->

| | |
|---|---|
| [Getting started](docs/getting-started.md) | 15 minutes from `uv add` to a scored experiment |
| [How OpenGrade works](docs/workflow.md) | the end-to-end workflow and the concepts behind it |
| [Python SDK](sdk/README.md) | tracing, experiments, metrics, production API |
| [CLI and CI](docs/08-cli-ci.md) | `opengrade evaluate` / `check`, config and policy reference, GitHub Actions |
| [Metrics and judges](docs/03-evaluation-engine.md) | built-in metrics, LLM judges, scoring, statistics |
| [Custom evaluators](docs/16-custom-evaluators.md) | Python metrics, custom LLM judges, server evaluators |
| [Security and API keys](docs/10-security-privacy.md) | trust model, API keys, content capture |
| [All docs](docs/README.md) | architecture, REST API, data model, glossary |
| [Changelog](CHANGELOG.md) | what changed in each release |

## Examples

| Example | Shows | Needs |
|---|---|---|
| [`sdk_tour`](examples/sdk_tour/README.md) | tracing, RAG verification, architecture/model sweeps, production metrics/alerts, prompt A/B | nothing (offline) |
| [`ci_regression_gate`](examples/ci_regression_gate/README.md) | PR vs `main` gate, baseline promotion | nothing (offline) |
| [`non_inferiority_gate`](examples/non_inferiority_gate/README.md) | requiring a PR to be *shown* not worse | nothing (offline) |
| [`llm_regression_gate`](examples/llm_regression_gate/README.md) | the same gate with a real LLM and an LLM judge | Ollama or an API key |
| [`sdk_hello`](examples/sdk_hello/README.md) | the smallest instrumented app | Ollama |

## Configure the LLM judges

Judges run on the server and use [LiteLLM](https://docs.litellm.ai/docs/providers). Put the
settings in a `.env` in the directory where you start `opengrade ui` (or in `backend/.env` with
Docker Compose; all options in [`backend/.env.example`](backend/.env.example)):

```bash
# Local Ollama
LLM_MODEL=ollama/gemma4:e2b
LLM_API_BASE=http://localhost:11434

# or a cloud provider
# LLM_MODEL=openai/gpt-4o-mini
# LLM_API_KEY=...
```

`opengrade ui` prints the judge model it picked up at startup. Judge methods, versioning and the
minimum model size: [LLM judges](docs/03-evaluation-engine.md#llm-judges).

## Deploy with Docker Compose

For a team server, CI baselines and production traffic, run the API, UI and PostgreSQL in containers:

```bash
cp backend/.env.example backend/.env   # judges, API key, other settings
docker compose up --build              # http://localhost:8000
```

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Before exposing the server beyond localhost, set `OPENGRADE_API_KEY`, create per-client keys and
terminate TLS at a reverse proxy: see [Security and API keys](docs/10-security-privacy.md). Behind a
proxy also set `FORWARDED_ALLOW_IPS`. OTLP ingest may return `429` / `503` with `Retry-After`
under load (limits in `backend/.env.example`). The local UI can use the same database:
`opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'`.

## Development

The repository holds the SDK (`sdk/`, package `opengrade-ai`), the API server (`backend/`, package
`opengrade-ai-server`) and the Next.js UI (`frontend/`). Python ≥ 3.12, Node.js ≥ 22.

```bash
python scripts/package_ui.py                          # build the UI into the server package
cd backend && uv sync --all-extras && uv run opengrade ui
cd sdk && uv sync && uv run pytest                    # SDK tests
cd frontend && npm ci && npm run dev                  # UI dev server on :3000, proxies /api
```

Docs site: the pages in `docs/` plus `sdk/README.md`, built with MkDocs Material
([`mkdocs.yml`](mkdocs.yml)) and deployed by [`.github/workflows/docs.yml`](.github/workflows/docs.yml)
on every push to `main`. The tools are the `docs` dependency group of `sdk/pyproject.toml`. Preview from the repo root:

```bash
uv run --project sdk --only-group docs mkdocs serve
```

`scripts/smoke_install.py` checks a clean install (`uv add` and `pip install`) of the built wheels
on Linux, macOS and Windows (*Install smoke* workflow, and against PyPI after each release).
Releases are published to PyPI from a `vX.Y.Z` tag with Trusted Publishing:
see [publishing](docs/08-cli-ci.md#publishing-to-pypi).

## License

[Apache-2.0](LICENSE)
