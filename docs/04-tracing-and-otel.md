# Tracing and OpenTelemetry

## Principle

Do not invent a proprietary tracing protocol.

Use OpenTelemetry as the transport/telemetry foundation and OpenInference/GenAI semantic conventions for AI-specific concepts.

OpenTelemetry Python supports traces and the SDK/API model. OpenTelemetry semantic conventions provide standardized attribute names. OpenInference extends the model for AI application observability.

## Ingestion

Initial options:

1. OTLP/HTTP ingestion endpoint.
2. OTLP/gRPC in a later milestone.
3. Native SDK helper for Python applications — delivered as [`sdk/README.md`](../sdk/README.md) (`pip install opengrade-ai`).

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

### Users, sessions, tags and metadata

Trace-level attributes use the OpenInference conventions and may sit on **any** span of the
trace (root span wins on conflicts, later batches merge in):

| Span attribute | Trace field | Notes |
|---|---|---|
| `user.id` (or `enduser.id`) | `user_id` | ≤ 200 chars |
| `session.id` (or `gen_ai.conversation.id`) | `session_id` | ≤ 200 chars |
| `tag.tags` | `tags` | list of strings (a JSON array string or a single string also work); union across spans, ≤ 50 |
| `metadata` | merged into `metadata` | JSON object string; `_`-prefixed keys are reserved and dropped; non-scalar values stored as JSON text; ≤ 50 keys |

The SDK writes them with `opengrade.set_user` / `set_session` / `set_tags` / `set_metadata` or
`opengrade.using_attributes(...)`; OpenInference's own `using_attributes` produces the same keys.
Tags and scalar metadata are indexed in `trace_attributes` (`key="tag"` or `metadata.<key>`) so
the trace list can filter by them (`?tag=…&metadata=key:value`).

## Privacy

Default policy:
- content capture OFF unless explicitly enabled
- configurable input/output redaction
- payload size limits
- PII redaction hook
- retention configuration
- no secrets stored in attributes

OpenTelemetry's current GenAI conventions explicitly warn that input/output message attributes may contain sensitive or PII data.

### Head sampling and attribute size

Server ingest can drop a fraction of traces before storage (`OTLP_TRACE_SAMPLE_RATE`, TraceIdRatioBased on the trace id) and truncate oversized span attribute / event / input/output strings (`OTLP_MAX_SPAN_ATTR_CHARS`). Dropped traces still return OTLP HTTP 200 so exporters do not retry. Sampling reduces what is stored and therefore how many live interactions / judges are created from those traces.

The SDK mirrors this with `init(trace_sample_rate=...)` / `OPENGRADE_TRACE_SAMPLE_RATE` (when opengrade owns the `TracerProvider`) and `init(max_capture_bytes=...)` / `OPENGRADE_MAX_CAPTURE_BYTES` for capture truncation. Trace head sampling is independent of `live_sample_rate` (judge) and `metrics_sample_rate`.

## Compatibility

The project should expose a documented compatibility matrix:

| Signal | v0.1 |
|---|---|
| OTLP HTTP | supported |
| OTLP gRPC | planned |
| OpenTelemetry Python | supported |
| Python SDK (`opengrade`) | supported (v0.1) |
| OpenInference attributes | supported where applicable |
| GenAI semantic conventions | supported/normalized |
| Instrumentor `openai` | documented / best-effort outside CI — `opengrade-ai[openai]` + `openai` |
| Instrumentor `anthropic` | documented / best-effort outside CI — `opengrade-ai[anthropic]` + `anthropic` |
| Instrumentor `langchain` | documented / best-effort outside CI — `opengrade-ai[langchain]` + LangChain |
| Instrumentor `llama_index` | documented / best-effort outside CI — `opengrade-ai[llama-index]` + `llama_index` |
| Instrumentor `bedrock` | documented / best-effort outside CI — `opengrade-ai[bedrock]` + Bedrock runtime (`boto3`) |

Install extras and manual smoke steps for tier-1 instrumentors: [`sdk/README.md`](../sdk/README.md).

Because GenAI semantic conventions are evolving, isolate normalization in one module so schema migrations do not affect the domain layer.
