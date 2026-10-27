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
- small scheduled / manual live smoke suite (`scripts/judge_sanity.py`; see `docs/03-evaluation-engine.md` and `.github/workflows/judge-sanity.yml.example`)

## Frontend

Playwright:
- create project
- inspect trace
- create dataset item
- run experiment
- view failed quality gate

Current smoke suite: `frontend/tests/e2e/smoke.spec.ts` (CI job `e2e`). It runs against the packaged UI served by `opengrade ui` on SQLite:

```bash
python scripts/package_ui.py
opengrade ui --backend-store-uri "sqlite+aiosqlite:///./e2e.db" &
cd frontend && npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 API_ORIGIN=http://127.0.0.1:8000 npm run test:e2e
```

Unit tests for UI logic: `npm test` (Node test runner, `*.test.ts`).

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
