# Architecture

## High-level architecture

```text
                           ┌──────────────────────┐
                           │      Next.js UI      │
                           │ TypeScript/Tailwind  │
                           └──────────┬───────────┘
                                      │ REST
                                      ▼
                           ┌──────────────────────┐
                           │       FastAPI        │
                           │      API layer       │
                           └──────────┬───────────┘
                                      │
                 ┌────────────────────┼────────────────────┐
                 │                    │                    │
                 ▼                    ▼                    ▼
          ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
          │ Trace       │      │ Evaluation  │      │ Regression  │
          │ Service     │      │ Engine      │      │ Engine      │
          └──────┬──────┘      └──────┬──────┘      └──────┬──────┘
                 │                    │                    │
                 └────────────────────┼────────────────────┘
                                      ▼
                             ┌──────────────────┐
                             │   PostgreSQL     │
                             └──────────────────┘

AI applications
      │
      │ OTLP / OpenTelemetry
      ▼
┌─────────────────────┐
│ Telemetry ingestion │
└─────────────────────┘
```

## Layering

### API
FastAPI routers, request/response schemas, pagination. No required auth middleware in v0.1.

### Application
Use cases such as:
- ingest trace
- create dataset
- run experiment
- evaluate sample
- compare experiments
- evaluate release policy

### Domain
Pure Python entities and policies. No FastAPI, SQLAlchemy, provider SDK, or UI dependency.

### Infrastructure
PostgreSQL repositories, LLM provider adapters, OpenTelemetry ingestion, background execution.

### Presentation
Next.js web app and Typer CLI.

## Repository structure

```text
repo/
├── backend/
│   ├── src/aiobs/
│   │   ├── api/
│   │   ├── application/
│   │   ├── domain/
│   │   ├── evaluation/
│   │   ├── tracing/
│   │   ├── regression/
│   │   ├── datasets/
│   │   ├── experiments/
│   │   ├── infrastructure/
│   │   └── main.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   └── package.json
├── docs/
├── examples/
├── migrations/
├── docker/
├── docker-compose.yml
└── .github/workflows/
```

## Platform boundaries

v0.1 is a self-hosted platform component, not a multi-tenant SaaS control plane.

- No built-in auth middleware is required for MVP.
- Project is an isolation/organization boundary for data, not a tenancy/billing model.
- Operators may place the stack behind reverse proxy, SSO, or private network controls.
- Extension happens through registries and adapters (evaluators, providers, redaction, normalization), not by embedding product-specific identity features in the domain.

## Architectural rules

1. Domain code must not import FastAPI.
2. Evaluation implementations depend on stable evaluator interfaces.
3. Provider SDKs are isolated behind adapters.
4. Database models do not leak into domain objects.
5. UI never calls providers directly.
6. All externally received telemetry is validated and size-limited.
7. Core must remain usable without an identity/auth subsystem.
