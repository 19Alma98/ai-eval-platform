# SDK hello (OpenAI-compatible → Ollama)

Emits one CHAIN span (`@aiobs.trace`) and an LLM child span from
`openinference-instrumentation-openai`.

## Prerequisites

1. Platform: `docker compose up --build` (API on `:8000`).
2. Project `demo` exists (see root README curl).
3. Ollama with a chat model: `ollama pull gemma4:e2b`.

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
