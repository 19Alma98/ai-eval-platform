# OpenGrade

Self-hosted AI evaluation & observability — traces, datasets, experiments, CI gates.

Open-source platform for AI quality engineering: turn production traces into datasets, run experiments, compare against a baseline, and fail CI on regressions. Packages: `opengrade-ai` (SDK) and `opengrade-ai-server` (API + UI); CLI `opengrade`.

**Not a fit:** open-ended agents where “good” is subjective, or as a substitute for live APM. The platform measures what you define; it does not invent a quality oracle. Details: [`docs/00-project-overview.md`](docs/00-project-overview.md).

```text
 trace your app ──▶ build a test set ──▶ run an experiment ──▶ compare with the baseline ──▶ CI gate
       ▲                                                                                     │
       └────────────── production traces, scores and alerts ◀────────── ship ◀───────────────┘
```

![OpenGrade walkthrough: overview, traces, experiments, baseline compare, quality gate, production judge](docs/images/hero.gif)

**[Get started in 15 minutes →](docs/getting-started.md)** — `uv` + `opengrade ui`, first trace, optional scored experiment.

**[SDK tour →](examples/sdk_tour/README.md)** — runnable, offline `uv` project: tracing, verifying a RAG against a gold set, comparing architectures and models, custom metrics and alerts in production.

[![CI](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/opengrade-ai)](https://pypi.org/project/opengrade-ai/)

## Quickstart (local UI)

Zero external infra — SQLite file + packaged UI in one process:

```bash
uv add 'opengrade-ai[ui]'
uv run opengrade ui   # http://127.0.0.1:8000 → ./opengrade.db
```

Pip: `pip install 'opengrade-ai[ui]'` then `opengrade ui` (same URL and `./opengrade.db`).

Optional Postgres (production / Compose):

```bash
opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

## Quickstart (Docker Compose)

Adopter-first path: follow [`docs/getting-started.md`](docs/getting-started.md) (`uv` + local UI, then optional experiment). Use Compose when you want Postgres and the full stack in containers.

```bash
cp backend/.env.example backend/.env   # optional but recommended
docker compose up --build
```
Copy the example when you want LLM judges or other overrides from [`backend/.env.example`](backend/.env.example).

Check liveness / readiness (single API replica only):

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Behind a reverse proxy, set `FORWARDED_ALLOW_IPS`. OTLP ingest may return `429`/`503` with `Retry-After` under load (see `backend/.env.example`).

## What it looks like

**1. Trace your app.** A decorator for the whole request, a `with` block for each step. OpenAI, Anthropic, LangChain, LlamaIndex and Bedrock calls become child spans automatically.

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

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | 15 minutes from `pip install` to a scored experiment |
| [SDK reference](sdk/README.md) | tracing, experiments, metrics, production API |
| [CLI and CI](docs/08-cli-ci.md) | `opengrade evaluate` / `check`, policy reference, GitHub Actions |
| [Evaluation engine](docs/03-evaluation-engine.md) | metrics, judges, scoring, statistics |
| [Custom evaluators](docs/16-custom-evaluators.md) | add a metric to the server |
| [All docs](docs/README.md) | architecture, API, data model, glossary |
| [Changelog](CHANGELOG.md) | what changed in each release |

## Examples

| Example | Shows | Needs |
|---|---|---|
| [`sdk_tour`](examples/sdk_tour/README.md) | tracing, RAG verification, architecture/model sweeps, production metrics/alerts, prompt A/B | nothing (offline) |
| [`ci_regression_gate`](examples/ci_regression_gate/README.md) | PR vs `main` gate, baseline promotion | nothing (offline) |
| [`non_inferiority_gate`](examples/non_inferiority_gate/README.md) | requiring a PR to be *shown* not worse | nothing (offline) |
| [`llm_regression_gate`](examples/llm_regression_gate/README.md) | the same gate with a real LLM and an LLM judge | Ollama or an API key |
| [`sdk_hello`](examples/sdk_hello/README.md) | the smallest instrumented app | Ollama |


## PyPI release

Packages: **`opengrade-ai`** (SDK) and **`opengrade-ai-server`** (API + UI). Publish via tag `vX.Y.Z` and [`.github/workflows/publish.yml`](.github/workflows/publish.yml) (Trusted Publishing). Setup and checklist: [`docs/08-cli-ci.md`](docs/08-cli-ci.md#publishing-to-pypi).

## Development

The repository holds the SDK (`sdk/`, package `opengrade-ai`), the API server (`backend/`,
package `opengrade-ai-server`) and the Next.js UI (`frontend/`). Python ≥ 3.12, Node.js ≥ 22.

```bash
python scripts/package_ui.py                          # build the UI into the server package
cd backend && uv sync --all-extras && uv run opengrade ui
cd sdk && uv sync && uv run pytest                    # SDK tests
cd frontend && npm ci && npm run dev                  # UI dev server on :3000, proxies /api
```

`scripts/smoke_install.py` checks a clean install (`uv add` and `pip install`) of the built wheels (run on Linux, macOS
and Windows by the *Install smoke* workflow, and against PyPI after each release). Releases are
published from a `vX.Y.Z` tag: see [publishing](docs/08-cli-ci.md#publishing-to-pypi).

### LLM judges (LiteLLM / Ollama)

LLM judges use LiteLLM. Settings live in `backend/.env` (see `.env.example`). For local Ollama the example sets:

```bash
LLM_MODEL=ollama/gemma4:e2b
LLM_API_BASE=http://localhost:11434
```

When creating an evaluator, use `"type": "llm_judge"` and `"config": {"kind": "correctness"}` (or `answer_relevance` / `groundedness` / `context_precision` / `context_recall`).

### RAG metrics naming

| opengrade `kind` | Notes |
|---|---|
| `groundedness` | Answer claims supported by retrieved docs |
| `answer_relevance` | Question–answer relevance (rubric) |
| `context_precision` | RAGAS-style average precision over retrieved docs |
| `context_recall` | Gold-answer claims covered by retrieved docs |
| `correctness` | Gold claims covered by the answer |
| `hit_at_k` / `recall_at_k` / `mrr` | Deterministic retrieval metrics on `expected_doc_ids` |


## Docs site
The files in `docs/` plus `sdk/README.md` are built with MkDocs Material (config: [`mkdocs.yml`](mkdocs.yml)) and deployed by [`.github/workflows/docs.yml`](.github/workflows/docs.yml) on every push to `main`. Preview locally with `uv run --no-project --with-requirements requirements-docs.txt mkdocs serve`. TODO: add site url

## License

[Apache-2.0](LICENSE)
