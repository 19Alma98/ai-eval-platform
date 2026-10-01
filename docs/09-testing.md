# Testing Strategy

## Backend

### Unit
Pure domain logic:
- policy evaluation
- score aggregation
- threshold handling
- evaluator parsing
- ID/version logic

### Integration
- PostgreSQL repositories
- API endpoints
- trace ingestion
- evaluator execution

### Contract
- OpenAPI schema
- OTLP ingestion payloads
- CLI/API compatibility

### Evaluation tests

Maintain a small deterministic golden dataset.

Example:

```text
fixtures/evals/
  groundedness/
  correctness/
  latency/
```

LLM judge tests must not rely on live providers for every CI run.

Use:
- mocked provider
- recorded fixtures
- small scheduled live smoke suite

## Frontend

Playwright:
- create project
- inspect trace
- create dataset item
- run experiment
- view failed release gate

## Load tests

Use k6 or Locust for:
- trace ingestion
- trace listing
- evaluation execution

Track:
- throughput
- p95/p99
- error rate

## Quality gates

CI should run:
- ruff
- mypy
- pytest
- coverage threshold
- frontend lint/typecheck
- Playwright smoke tests
- dependency/security scan
- Docker build
