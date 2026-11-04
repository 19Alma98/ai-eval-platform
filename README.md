# OpenGrade

[![CI](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/opengrade-ai)](https://pypi.org/project/opengrade-ai/)
[![Python](https://img.shields.io/pypi/pyversions/opengrade-ai)](https://pypi.org/project/opengrade-ai/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Unit tests for your LLM app: fail the pull request when quality drops.**

OpenGrade is a self-hosted, open-source platform for AI quality engineering. You trace your app,
keep a gold test set, run experiments against it, compare each run with the last accepted one, and
let CI block the regressions. The same metrics then keep watching the app in production.

```text
 trace your app ──▶ build a test set ──▶ run an experiment ──▶ compare with the baseline ──▶ CI gate
       ▲                                                                                     │
       └────────────── production traces, scores and alerts ◀────────── ship ◀───────────────┘
```

![OpenGrade walkthrough: overview, traces, experiments, baseline compare, quality gate, production judge](docs/images/hero.gif)

## Try it in one minute

```bash
uvx --from 'opengrade-ai[ui]' opengrade ui   # UI + API on http://127.0.0.1:8000, data in ./opengrade.db
```

One process, one SQLite file, no Docker. In a project: `uv add 'opengrade-ai[ui]'` then
`uv run opengrade ui`. With pip: `pip install 'opengrade-ai[ui]'` then `opengrade ui`.

Then follow **[Getting started in 15 minutes →](docs/getting-started.md)** (first trace, first
scored experiment) or the offline **[SDK tour →](examples/sdk_tour/README.md)** (no GPU, no API key).

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
print(result.summary())
```

**3. Gate the pull request.** A YAML policy, an exit code for CI:

```yaml
# opengrade.yaml
evaluate:
  task: rag_app:task
  dataset: gold.jsonl
  metrics: [hit_at_k, must_contain, latency]
  baseline: alias:main

hit_at_k: { min: 0.8 }               # absolute floor
latency:  { p95_max_ms: 2000 }
regression:
  max_delta: -0.05                   # significant drop of the mean vs main → fail
  max_new_failures: 0                # a test case that passes on main must not fail
critical: { by: critical }           # must-pass test cases
```

```console
$ opengrade evaluate --config opengrade.yaml --require-baseline
Test cases worse than baseline (4):
  ▼ How often are laptops refreshed?
      hit_at_k: 1.000 PASS → 0.000 FAIL
      candidate: I don't know.
regression.hit_at_k.mean_score       -0.20   -0.05   failed
regression.hit_at_k.new_failures      4       0      failed
Result: FAILED                                         # exit code 1 → the PR check is red
```

On `main`, `--promote main` makes a passing run the new baseline. Reports for the job summary
(`--report-md`) and JUnit (`--junit`) are built in. Runnable version, no LLM needed:
[`examples/ci_regression_gate`](examples/ci_regression_gate/README.md).

## Features

| | |
|---|---|
| **Tracing** | OTLP / OpenInference ingest (`POST /v1/traces`), `@opengrade.trace`, `opengrade.span`, users, sessions, tags and metadata, trace waterfall with RAG view. Any OpenTelemetry exporter works. |
| **Test sets** | Versioned gold datasets from JSONL / CSV / DataFrames or promoted from production traces; RAG Q&A, classification and tool-calling task types. |
| **Metrics** | Deterministic (`hit_at_k`, `recall_at_k`, `mrr`, `exact_match`, `must_contain`, `regex`, `json_schema`, `tool_call_success`, latency, tokens, cost), LLM judges via [LiteLLM](https://docs.litellm.ai/) (`groundedness`, `correctness`, `answer_relevance`, `context_precision`, `context_recall`, `citation_accuracy`, `refusal`), custom judges and Python metrics. Local models via Ollama. |
| **Experiments** | `evaluate`, `sweep` (grid of models / prompts / chunk sizes), `evaluate_retrieval`, `repeats=N` for flaky pipelines, `group_by` per category, git revision of every run, side-by-side compare. |
| **CI gate** | Absolute thresholds, paired-bootstrap regression check, new failures per test case, critical cases, per-group checks, non-inferiority, statistical-power warning, baseline aliases, Markdown + JUnit reports. Exit codes `0` pass, `1` fail, `2` config error, `3` infra error. |
| **Production** | Online judges on live traffic, user feedback, custom production metrics, alert rules (thresholds, drift, anomalies) with webhooks, release / environment comparison, retention per project. |
| **Deployment** | `opengrade ui` (SQLite) or Docker Compose / your own Postgres; migrations run on startup; optional API keys with `admin` / `read` / `ingest` scopes. |

## Is it a fit?

**Good fit:** apps where "correct" can be checked: RAG and FAQ assistants, classification,
structured extraction, tool calling with fixed schemas, plus latency / cost / error budgets.

**Not a fit:** open-ended agents where "good" is subjective, or a replacement for your APM.
OpenGrade measures what you define; it does not invent a quality oracle. More in
[`docs/00-project-overview.md`](docs/00-project-overview.md).

**Compared with other tools:** tracing platforms (Langfuse, Arize Phoenix…) and metric libraries
(Ragas, DeepEval, promptfoo…) cover parts of this loop. OpenGrade's focus is the step in between:
a statistically sound *"is this PR worse than main?"* gate, on a test set grown from your own
traces, self-hosted in one process. It speaks OpenTelemetry / OpenInference, so it can sit next
to the tools you already use.

## Deploy

| Mode | Command | For |
|---|---|---|
| Local | `opengrade ui` | trying it, single developer, CI with an embedded store |
| Postgres | `opengrade ui --backend-store-uri 'postgresql+asyncpg://user:pass@host/db'` | a shared team server |
| Docker Compose | `cp backend/.env.example backend/.env && docker compose up --build` | API + UI + Postgres in containers |

- **Security.** Without `OPENGRADE_API_KEY` the server is open: keep it on localhost or a private
  network. To expose it, set `OPENGRADE_API_KEY` (bootstrap admin key), serve it over HTTPS and
  create one key per app (`ingest`), person (`read`) or CI job (`admin`) in **Settings → API keys**
  or with `opengrade keys create`. Span inputs/outputs are stored by default; set
  `CONTENT_CAPTURE_ENABLED=false` to keep only structure, timings and scores. See
  [security & privacy](docs/10-security-privacy.md).
- **LLM judges** need a model: `LLM_MODEL=ollama/gemma4:e2b` + `LLM_API_BASE=http://localhost:11434`
  for a local one, or a cloud model + `LLM_API_KEY`. Without one, tracing and deterministic metrics
  still work. All settings: [`backend/.env.example`](backend/.env.example).
- **Operations** (single API replica, `/health` and `/ready`, reverse proxy, backpressure, SQLite
  backups): [`backend/README.md`](backend/README.md).

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
| [`sdk_tour`](examples/sdk_tour/README.md) | tracing, RAG verification, model comparison, production metrics and alerts | nothing (offline) |
| [`ci_regression_gate`](examples/ci_regression_gate/README.md) | PR vs `main` gate, baseline promotion | nothing (offline) |
| [`non_inferiority_gate`](examples/non_inferiority_gate/README.md) | requiring a PR to be *shown* not worse | nothing (offline) |
| [`llm_regression_gate`](examples/llm_regression_gate/README.md) | the same gate with a real LLM and an LLM judge | Ollama or an API key |
| [`hr_it_assistant`](examples/hr_it_assistant/README.md) | end-to-end RAG demo comparing two local models | Docker Compose + Ollama |
| [`sdk_hello`](examples/sdk_hello/README.md) | the smallest instrumented app | Ollama |

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

## License

[Apache-2.0](LICENSE)
