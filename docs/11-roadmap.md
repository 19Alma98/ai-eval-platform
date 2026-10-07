# Implementation Roadmap

## Phase 0 — foundation

Deliver:
- monorepo
- backend package
- frontend shell
- PostgreSQL
- Docker Compose (trusted local network)
- CI
- health endpoint
- README note on self-hosted / no built-in auth

Definition of done:
```bash
docker compose up
curl /health
```

## Phase 1 — tracing

Deliver:
- OTLP HTTP ingestion
- trace/span persistence
- trace explorer
- Python example app
- Python SDK helper (`sdk/`, package `aiobs`; completes “Native SDK helper” in tracing docs)

Demo:
instrument a tiny AI app and inspect a real trace.

## Phase 2 — evaluation engine

Deliver:
- evaluator interface
- deterministic evaluators
- one LLM judge
- evaluation results
- dataset creation

## Phase 3 — experiments

Deliver:
- experiment runs
- baseline comparison
- aggregate metrics
- result visualization

## Phase 4 — release gates

Deliver:
- YAML policy
- CLI
- exit codes
- GitHub Actions example

This is the MVP milestone.

## Phase 5 — human feedback

Deliver:
- review UI
- labels
- comments
- promote trace to dataset

Partial delivery via **AI Eval Run** (`LiveInteraction`): SDK submit → background gold-less judge → Live runs UI with agree/disagree + promote to TestSet. Generic Review entity / assign-SLA workflow remains later.

## Phase 6 — production hardening

Deliver:
- rate limits
- retention
- redaction
- background workers
- load tests
- security hardening
- deployment docs for trusted-network / reverse-proxy setups

Optional overlay (only if operators need it; not an MVP gate):
- static API key or reverse-proxy identity header

Built-in SSO/RBAC remains out of scope unless the project later decides to own identity as a platform feature.

## Phase 7 — scale

Only if benchmarks justify:
- ClickHouse
- object storage
- async ingestion
- Kubernetes deployment

## Phase 8 — extensibility surface

Deliver for community/platform adoption:
- documented evaluator registry
- provider adapter guide
- redaction hook guide
- compatibility matrix for OTLP / OpenInference / GenAI conventions
- contribution guide for plugins without core forks
