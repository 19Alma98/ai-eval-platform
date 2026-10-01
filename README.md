# AI Evaluation & Observability Platform

Open-source, self-hosted platform for AI quality engineering.

**Deployment model (v0.1):** trusted network only (localhost / private Docker network). There is **no built-in authentication**. Do not expose the stack on a public network without an external auth layer (reverse proxy, VPN, or cluster network policy).

## Quickstart

```bash
docker compose up --build
```

Check health:

```bash
curl http://localhost:8000/health
```

Create a project:

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "content-type: application/json" \
  -d "{\"name\":\"Demo\",\"slug\":\"demo\"}"
```

List projects:

```bash
curl http://localhost:8000/api/v1/projects
```

### Ingest a trace (OTLP/HTTP)

Send OTLP JSON or protobuf to `POST /v1/traces` with exactly one of `X-Project-Id` or `X-Project-Slug`:

```bash
curl -X POST http://localhost:8000/v1/traces \
  -H "content-type: application/json" \
  -H "X-Project-Slug: demo" \
  -d "{\"resourceSpans\":[{\"scopeSpans\":[{\"spans\":[{\"traceId\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"spanId\":\"bbbbbbbbbbbbbbbb\",\"name\":\"hello\",\"startTimeUnixNano\":\"1700000000000000000\",\"endTimeUnixNano\":\"1700000001000000000\",\"status\":{\"code\":\"STATUS_CODE_OK\"},\"attributes\":[{\"key\":\"openinference.span.kind\",\"value\":{\"stringValue\":\"CHAIN\"}}]}]}]}]}"
```

Or run the Python example:

```bash
cd examples/otlp_hello
pip install -r requirements.txt
set AIOBS_PROJECT_SLUG=demo
python main.py
```

### List / get traces

```bash
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces"
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces/<otel-trace-id-hex>"
```

## Release gate (Phase 4)

After evaluating an experiment, check a YAML policy:

```bash
cd cli && uv sync
uv run aiobs check --policy ../examples/aiobs.yaml \
  --base-url http://localhost:8000 \
  --project-id <project-uuid> \
  --experiment-id <experiment-uuid>
```

Exit codes: `0` pass, `1` gate failed, `2` config error, `3` infra error. Example workflow: [`.github/workflows/release-gate.yml.example`](.github/workflows/release-gate.yml.example). Design: [`docs/superpowers/specs/2026-10-01-phase4-release-gates-design.md`](docs/superpowers/specs/2026-10-01-phase4-release-gates-design.md).

## Documentation

Technical specification lives in [`docs/`](docs/). Phase 1 design: [`docs/superpowers/specs/2026-09-30-phase1-otlp-traces-design.md`](docs/superpowers/specs/2026-09-30-phase1-otlp-traces-design.md).

## Development (backend)

```bash
cd backend
cp .env.example .env   # edit as needed
uv sync --all-extras
uv run alembic upgrade head
uv run uvicorn aiobs.main:app --reload --host 0.0.0.0 --port 8000
```

Requires PostgreSQL. With Compose, Postgres is published on host port **5434** (`DATABASE_URL=postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs`).

### LLM judges (LiteLLM / Ollama)

LLM judges use LiteLLM. Settings live in `backend/.env` (see `.env.example`). For local Ollama the example sets:

```bash
LLM_MODEL=ollama/gemma4:e2b
LLM_API_BASE=http://localhost:11434
```

When creating an evaluator, use `"type": "llm_judge"` and `"config": {"kind": "correctness"}` (or `answer_relevance` / `groundedness`).
