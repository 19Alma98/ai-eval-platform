# SDK hello (OpenAI-compatible → Ollama)

Emits one CHAIN span (`@aiobs.trace`) and an LLM child span from
`openinference-instrumentation-openai`.

## Prerequisites

1. Platform: `docker compose up --build` (API on `:8000`).
2. Ollama with a chat model: `ollama pull gemma4:e2b`.

## Run

```bash
cd sdk && uv sync --extra openai --extra dev && cd ..
cd examples/sdk_hello
uv run --directory ../../sdk --with openai python main.py
# or: pip install -r requirements.txt && python main.py
```

Expected UI: one trace under project **demo**, parent CHAIN + child LLM.

`CONTENT_CAPTURE_ENABLED` on the API still controls whether the platform stores
`input`/`output` bodies; the SDK emits attributes independently.

## Troubleshooting / failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Connection refused / timeout to `:8000` | Platform API not running | Start `docker compose up --build` from repo root; confirm `curl http://localhost:8000/health` (or your API health route) succeeds. |
| OTLP export errors, no traces in UI | Wrong `AIOBS_TRACKING_URI` | Default is local `:8000`; OTLP goes to `<uri>/v1/traces`. Project **demo** is created on first run. |
| Empty trace list for **demo** | Export failed silently or wrong project slug | Check script env and API logs; verify `AIOBS_PROJECT_SLUG` is what you expect. |
| Connection error to `:11434` | Ollama not running | Start Ollama; confirm `curl http://localhost:11434/api/tags`. |
| Model not found / 404 from Ollama | Model not pulled | Run `ollama pull gemma4:e2b` (or point `OpenAI` client at a model you have). |
| Script runs but UI shows spans without text | Content capture off on API | Expected when `CONTENT_CAPTURE_ENABLED` is false; spans still appear without stored bodies. |
