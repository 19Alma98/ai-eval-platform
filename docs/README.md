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
2. [Python SDK](sdk.md) — tracing, experiments, custom metrics and judges, control-plane client
3. [CLI and CI](08-cli-ci.md) — `opengrade evaluate` / `opengrade check`, baselines, quality gates in GitHub Actions
4. [Metrics and judges](03-evaluation-engine.md) — built-in evaluators, LLM judges, scoring
5. [Custom evaluators](16-custom-evaluators.md) — adding a server-side evaluator
6. [Security and API keys](10-security-privacy.md) — deployment model, keys, content capture
7. [Examples](examples.md) — runnable demos, from a first trace to a PR regression gate
8. [API reference](reference/index.md) — generated from the SDK docstrings

Root [`README.md`](../README.md): quickstart with Docker Compose and ops notes.

## Design notes

Internal specifications and decisions, for contributors.

- [Project overview](00-project-overview.md), [architecture](01-architecture.md), [domain model](02-domain-model.md)
- [Tracing and OpenTelemetry](04-tracing-and-otel.md), [REST API](05-api.md), [database](06-database.md), [frontend](07-frontend.md)
- [Testing strategy](09-testing.md), [roadmap](11-roadmap.md)
- [MVP user stories](12-mvp-user-stories.md), [definition of done](15-definition-of-done.md)
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
| **Project** | Tenant-like workspace (slug + id) for traces, test sets, and runs |
| **Test set** | Versioned gold dataset (e.g. `rag_qa` questions with expected answers) |
| **Metrics pack** | Named set of evaluators (deterministic and/or LLM judges) scored on a run |
| **Experiment / Run** | One scored pass of an app/config over a test set (often bound to traces) |
| **Quality gate** | YAML policy + `opengrade check` — exit codes for CI |
| **Live run** | Production-like interaction scored without gold; can promote into a test set |
| **Trace** | OTLP/OpenInference span tree ingested at `/v1/traces` |

Primary RAG loop: **Project → test set → metrics pack → evaluate → compare / quality gate**.
