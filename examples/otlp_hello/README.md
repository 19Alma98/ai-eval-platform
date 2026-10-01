# OTLP Hello Example

Tiny OpenTelemetry Python app that exports one span to the platform OTLP endpoint.

## Prerequisites

1. Platform running (`docker compose up --build` or local uvicorn + Postgres).
2. A project exists (slug `demo` by default):

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "content-type: application/json" \
  -d "{\"name\":\"Demo\",\"slug\":\"demo\"}"
```

## Run

```bash
cd examples/otlp_hello
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -r requirements.txt

set AIOBS_PROJECT_SLUG=demo
python main.py
```

Or with project UUID:

```bash
set AIOBS_PROJECT_ID=<project-uuid>
python main.py
```

## Inspect

```bash
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces"
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces/<trace-id>"
```
