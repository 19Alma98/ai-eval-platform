# OpenGrade — Docs

Self-hosted AI evaluation & observability. Open-source, not a hosted SaaS.

**Scope:** CI regression gates for checkable AI apps (RAG, classification, structured extraction, fixed-schema tool calling). Not an oracle for open-ended agents — see fit / non-fit in [`00-project-overview.md`](00-project-overview.md).

## Naming

| What you see | What it means |
|---|---|
| **OpenGrade** | Product name |
| `opengrade-ai` | PyPI SDK (`import opengrade`, console script `opengrade`) |
| `opengrade-ai-server` | PyPI API + packaged UI (`opengrade_server`, `opengrade-server`) |
| `opengrade ui` / `opengrade check` | CLI commands (need server / `[ui]` extra) |

## Start here (adopters)

1. [`getting-started.md`](getting-started.md) — 15 minutes: `uv` + UI + first trace (+ optional experiment)
2. Root [`README.md`](../README.md) — quickstart (Compose or `opengrade ui`) and ops notes
3. [`examples/sdk_hello/README.md`](../examples/sdk_hello/README.md) — instrument → see a trace
4. [`examples/hr_it_assistant/README.md`](../examples/hr_it_assistant/README.md) — dataset → metrics → experiment → gate
5. [`sdk/README.md`](../sdk/README.md) — SDK reference

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

## Technical specs (implementation)

1. [`00-project-overview.md`](00-project-overview.md)
2. [`01-architecture.md`](01-architecture.md)
3. [`02-domain-model.md`](02-domain-model.md)
4. [`03-evaluation-engine.md`](03-evaluation-engine.md)
5. [`04-tracing-and-otel.md`](04-tracing-and-otel.md)
6. [`05-api.md`](05-api.md)
7. [`06-database.md`](06-database.md)
8. [`07-frontend.md`](07-frontend.md)
9. [`08-cli-ci.md`](08-cli-ci.md)
10. [`09-testing.md`](09-testing.md)
11. [`10-security-privacy.md`](10-security-privacy.md)
12. [`11-roadmap.md`](11-roadmap.md)
13. [`12-mvp-user-stories.md`](12-mvp-user-stories.md)
14. [`16-custom-evaluators.md`](16-custom-evaluators.md) — contributor guide: adding an evaluator

Architecture decisions: [`13-adr-001.md`](13-adr-001.md), [`14-adr-002.md`](14-adr-002.md).

Completion criteria: [`15-definition-of-done.md`](15-definition-of-done.md).
