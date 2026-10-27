# Security and Privacy

## Trust model (v0.1)

The platform is **self-hosted and network-trusted by default**.

Access control for v0.1 is an **infrastructure concern**:
- bind to localhost for local demos;
- place behind VPN / private cluster network;
- terminate TLS and identity at a reverse proxy when exposing beyond trusted networks.

Built-in authentication, SSO, and RBAC are explicitly out of scope for MVP.

## Threat model

Primary risks:
- prompt/response data leakage
- malicious telemetry payloads
- SSRF through provider/tool metadata
- oversized payloads
- arbitrary evaluator code
- secret leakage
- unsafe rendering of model output
- accidental exposure of an unauthenticated stack on a public network

## Rules

1. Never execute evaluator code received from users.
2. Custom evaluators are trusted Python packages in v0.1.
3. Limit payload sizes.
4. Sanitize/escape rendered content.
5. Provider credentials are server-side secrets.
6. Never log API keys or provider secrets.
7. Allow content capture to be disabled (see [Content capture and redaction](#content-capture-and-redaction)).
8. Provide redaction controls: server-wide at ingestion, per function in the SDK.
9. Validate URLs if remote resources are ever supported.
10. Use dependency scanning in CI.
11. Document that public exposure without an external auth layer is unsupported.
12. Make the content-capture default explicit and easy to turn off (it is on by default; see below).

## Data classification

Trace fields should be classified:
- metadata
- operational
- potentially sensitive content
- secret/prohibited

Input/output content is captured by default (live scoring and the RAG view need it); turn it off as described below.

## Content capture and redaction

Span text (inputs, outputs, prompts, completions, retrieved document text) is the potentially sensitive part of a trace. It can be dropped at two points.

### Server: `CONTENT_CAPTURE_ENABLED`

Default `true`. With `CONTENT_CAPTURE_ENABLED=false` the API redacts every OTLP batch **at ingestion, before anything is written to the database**:

| Dropped | Kept |
| --- | --- |
| `input.value`, `output.value`, `input.mime_type`, `output.mime_type` | span names, kinds, status, timings |
| LLM prompts/messages/completions: `llm.input_messages`, `llm.output_messages`, `llm.prompts`, `llm.prompt_template.*`, `gen_ai.prompt`, `gen_ai.completion`, `gen_ai.input.messages`, `gen_ai.output.messages`, including flattened forms such as `llm.input_messages.0.message.content` | token counts, cost, model name, other attributes |
| Embedding input text (`embedding.embeddings.N.embedding.text`) | |
| Document text in `retrieval.documents`, `reranker.*_documents`, `documents` (`text`, `content`, `page_content`, flattened `N.document.content`) | document ids, titles, scores, metadata |
| Trace-level `input` / `output` | trace metadata, environment, user/session ids |

Consequences: retrieval metrics that use ids (hit@k, recall, MRR) still work; judges that need document text (groundedness, context precision/recall) return SKIPPED; no live answer is created from a trace, so live scoring does not run. The UI shows "—" for redacted I/O.

Implementation: `backend/src/opengrade_server/tracing/redaction.py`; covered by `backend/tests/test_tracing_normalization.py`.

```bash
CONTENT_CAPTURE_ENABLED=false docker compose up   # Compose (or put it in the root .env)
CONTENT_CAPTURE_ENABLED=false opengrade ui        # local server (or backend/.env)
```

### SDK: per function

`@opengrade.trace` records arguments and the return value as `input.value` / `output.value`. Turn this off where a function handles secrets or personal data, so the text never leaves the process:

```python
@opengrade.trace(capture_input=False, capture_output=False)
def lookup_customer(customer_id: str, api_key: str) -> dict: ...
```

`OPENGRADE_DISABLED=1` disables the SDK entirely (no spans, scores or feedback are sent).

Spans emitted by auto-instrumentation (OpenInference instrumentors for OpenAI, LangChain, LlamaIndex, …) follow their own settings; use the server switch above to guarantee nothing is stored.

### Not yet available

- Per-argument include/exclude and a user-supplied redaction callback in the SDK (pattern-based PII scrubbing).
- Retention/TTL for stored traces.

Until then, use the two switches above, or put a redacting OpenTelemetry Collector processor in front of `/v1/traces`.

## Future (optional platform overlays)

These remain optional and should not reshape the domain core:

- optional API key / reverse-proxy identity header
- workspace RBAC
- SSO/OIDC
- encryption-at-rest documentation
- audit logs
- configurable retention
