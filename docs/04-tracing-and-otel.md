# Tracing and OpenTelemetry

## Principle

Do not invent a proprietary tracing protocol.

Use OpenTelemetry as the transport/telemetry foundation and OpenInference/GenAI semantic conventions for AI-specific concepts.

OpenTelemetry Python supports traces and the SDK/API model. OpenTelemetry semantic conventions provide standardized attribute names. OpenInference extends the model for AI application observability.

## Ingestion

Initial options:

1. OTLP/HTTP ingestion endpoint.
2. OTLP/gRPC in a later milestone.
3. Native SDK helper for Python applications — delivered as [`sdk/README.md`](../sdk/README.md) (`pip install aiobs-eval`).

## Trace normalization

Incoming telemetry is normalized into:

```text
Trace
  └── Span
       ├── attributes
       ├── events
       └── children
```

AI-specific span metadata should preserve:
- provider
- model
- operation
- input/output where enabled
- token counts
- retrieval metadata
- tool calls
- latency
- errors

Do not assume prompt/completion content is always safe to store.

## Privacy

Default policy:
- content capture OFF unless explicitly enabled
- configurable input/output redaction
- payload size limits
- PII redaction hook
- retention configuration
- no secrets stored in attributes

OpenTelemetry's current GenAI conventions explicitly warn that input/output message attributes may contain sensitive or PII data.

## Compatibility

The project should expose a documented compatibility matrix:

| Signal | v0.1 |
|---|---|
| OTLP HTTP | supported |
| OTLP gRPC | planned |
| OpenTelemetry Python | supported |
| Python SDK (`aiobs`) | supported (v0.1) |
| OpenInference attributes | supported where applicable |
| GenAI semantic conventions | supported/normalized |
| Instrumentor `openai` | documented / best-effort outside CI — `aiobs[openai]` + `openai` |
| Instrumentor `anthropic` | documented / best-effort outside CI — `aiobs[anthropic]` + `anthropic` |
| Instrumentor `langchain` | documented / best-effort outside CI — `aiobs[langchain]` + LangChain |
| Instrumentor `llama_index` | documented / best-effort outside CI — `aiobs[llama-index]` + `llama_index` |
| Instrumentor `bedrock` | documented / best-effort outside CI — `aiobs[bedrock]` + Bedrock runtime (`boto3`) |

Install extras and manual smoke steps for tier-1 instrumentors: [`sdk/README.md`](../sdk/README.md).

Because GenAI semantic conventions are evolving, isolate normalization in one module so schema migrations do not affect the domain layer.
