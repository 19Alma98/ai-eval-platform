# OpenGrade

Self-hosted AI evaluation & observability. Open-source, not a hosted SaaS.

**Scope:** CI regression gates for checkable AI apps (RAG, classification, structured extraction, fixed-schema tool calling). Not an oracle for open-ended agents — see fit / non-fit in the [project overview](00-project-overview.md).

![OpenGrade walkthrough: overview, traces, experiments, baseline compare, quality gate, production judge](images/hero.gif)

```bash
uv add 'opengrade-ai[ui]'
uv run opengrade ui   # http://127.0.0.1:8000
```

**[Get started in 15 minutes →](getting-started.md)**

## User guide

For people adopting OpenGrade in their app and CI.

1. [Getting started](getting-started.md) — 15 minutes: `uv` + UI + first trace (+ optional experiment)
2. [How OpenGrade works](workflow.md) — the end-to-end workflow: what runs where, test sets, metrics, baselines, CI gate, production
3. [Python SDK](sdk.md) — tracing, experiments, custom metrics and judges, control-plane client
4. [CLI and CI](08-cli-ci.md) — `opengrade evaluate` / `opengrade check`, config and policy reference, quality gates in GitHub Actions
5. [Metrics and judges](03-evaluation-engine.md) — built-in evaluators, LLM judges, scoring
6. [Custom evaluators](16-custom-evaluators.md) — adding a server-side evaluator
7. [Security and API keys](10-security-privacy.md) — deployment model, keys, content capture
8. [Examples](examples.md) — runnable demos, from a first trace to a PR regression gate
9. [API reference](reference/index.md) — generated from the SDK docstrings

Root [`README.md`](../README.md): requirements, Docker Compose deployment, development setup.

## Design notes

Internal specifications and decisions, for contributors.

- [Project overview](00-project-overview.md), [architecture](01-architecture.md), [domain model](02-domain-model.md)
- [Tracing and OpenTelemetry](04-tracing-and-otel.md), [REST API](05-api.md), [database](06-database.md), [frontend](07-frontend.md)
- [Testing strategy](09-testing.md), [roadmap](11-roadmap.md)
- Architecture decisions: [ADR-001](13-adr-001.md) (OpenTelemetry/OpenInference), [ADR-002](14-adr-002.md) (PostgreSQL first)

## Naming

| What you see | What it means |
|---|---|
| **OpenGrade** | Product name |
| `opengrade-ai` | PyPI SDK (`import opengrade`, console script `opengrade`) |
| `opengrade-ai-server` | PyPI API + packaged UI (`opengrade_server`, `opengrade-server`) |
| `opengrade ui` / `opengrade check` | CLI commands (need server / `[ui]` extra) |

## Glossary

| Term | Meaning |
|---|---|
| **Project** | Workspace for traces, datasets and experiments (slug + id) |
| **Trace** | OTLP/OpenInference span tree of one request, ingested at `/v1/traces` |
| **Dataset** / **test set** | Versioned gold items (e.g. `rag_qa` questions with expected answers and documents). *Test set* in the UI, `dataset` in the SDK and API |
| **Metric** / **evaluator** | Scores one answer: deterministic, LLM judge, custom judge or local Python metric |
| **Metrics set** | Named, versioned set of metrics with thresholds scored on an experiment. *Metrics pack* in older routes (`evaluate-pack`, `metrics_packs`) |
| **Experiment** / **run** | One scored pass of your app over a dataset |
| **Baseline** / **alias** | The experiment a run is compared with; an alias (`alias:main`) points to the last accepted one |
| **Quality gate** | YAML policy + `opengrade evaluate` / `opengrade check`: exit codes for CI |
| **Live interaction** / **live run** | Production request scored without gold; can be promoted into a dataset |

Primary loop: **project → dataset → metrics set → experiment → compare with the baseline → quality gate → production → promote into the dataset**. Explained step by step in [How OpenGrade works](workflow.md).
