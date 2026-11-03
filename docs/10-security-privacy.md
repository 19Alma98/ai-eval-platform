# Security and Privacy

## Trust model (v0.1)

The platform is **self-hosted and network-trusted by default**.

Without `OPENGRADE_API_KEY` the server is open: bind it to localhost or keep it on a VPN /
private cluster network.

To expose it beyond a trusted network, set an **API key** (see [API key](#api-key)) and
terminate **TLS** at a reverse proxy (Caddy, Traefik, the cloud load balancer). Without HTTPS the
key travels in clear text and protects nothing.

There are **no user accounts**: keys identify machines (SDK, CI, OTel exporters) and the
dashboard. SSO, if needed, goes in a reverse proxy in front (oauth2-proxy, Cloudflare Access).
RBAC is out of scope.

## API key

Set `OPENGRADE_API_KEY` on the server (a long random value, e.g. `openssl rand -hex 32`). Then:

- every `/api/*` request and OTLP `POST /v1/traces` needs `Authorization: Bearer <key>`,
  otherwise `401`; `/health`, `/ready` and the static UI files stay public;
- the SDK sends the header when `OPENGRADE_API_KEY` is set in the app's environment (or via
  `opengrade.set_api_key()` / `Client(api_key=...)`), on HTTP calls and OTLP export alike; it
  warns once when the key would go over plain `http://` to a non-loopback host;
- a plain OpenTelemetry exporter uses
  `OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <key>"`;
- the dashboard asks for the key once and exchanges it for a session cookie
  (`HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS, `OPENGRADE_UI_SESSION_HOURS`, default 12).
  The cookie is an expiring HMAC signature, not the key; it is not a user login.

**Rotation:** set the new key in `OPENGRADE_API_KEY` and the old one in
`OPENGRADE_API_KEY_PREVIOUS`, restart, move every client to the new key, then remove the
previous one and restart again. UI sessions signed with a key stop working when that key is no
longer accepted.

This single key has full access (`admin`). Per-client keys with `read` / `ingest` scopes and a
Settings page to manage them are planned (see `TODO.md`).

## Threat model

Primary risks:
- prompt/response data leakage
- malicious telemetry payloads
- SSRF through provider/tool metadata
- oversized payloads
- arbitrary evaluator code
- secret leakage
- unsafe rendering of model output
- accidental exposure of an unauthenticated stack on a public network (no `OPENGRADE_API_KEY`)

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
11. Public exposure requires `OPENGRADE_API_KEY` and HTTPS; never log the `Authorization` header.
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

- API keys per client with `read` / `ingest` scopes (phase 2)
- reverse-proxy identity header
- workspace RBAC
- SSO/OIDC
- encryption-at-rest documentation
- audit logs
- configurable retention
