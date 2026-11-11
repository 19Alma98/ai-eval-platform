# Security and Privacy

## Trust model (v0.1)

The platform is **self-hosted and network-trusted by default**.

Without `OPENGRADE_API_KEY` the server is open: bind it to localhost or keep it on a VPN /
private cluster network.

To expose it beyond a trusted network, set an **API key** (see [API keys](#api-keys)) and
terminate **TLS** at a reverse proxy (Caddy, Traefik, the cloud load balancer). Without HTTPS the
key travels in clear text and protects nothing.

There are **no user accounts**: keys identify machines (SDK, CI, OTel exporters) and the
dashboard. SSO, if needed, goes in a reverse proxy in front (oauth2-proxy, Cloudflare Access).
Beyond the three key scopes below, RBAC is out of scope.

## API keys

Set `OPENGRADE_API_KEY` on the server (a long random value, e.g. `openssl rand -hex 32`). It
turns auth on and is the bootstrap **admin** key. Without it the server is open and no key is
checked. Then:

- every `/api/*` request and OTLP `POST /v1/traces` needs `Authorization: Bearer <key>`,
  otherwise `401`; a valid key outside its scope gets `403`. After too many failed attempts from the same client IP (default 60/min, then a 60s lockout; set `OPENGRADE_AUTH_FAILED_ATTEMPTS_PER_MINUTE=0` to disable), the server responds `429` with `Retry-After`. `/health`, `/ready`, the auth endpoints and the static UI files stay public (session create still counts failed keys);
- the SDK sends the header when `OPENGRADE_API_KEY` is set in the app's environment (or via
  `opengrade.set_api_key()` / `Client(api_key=...)`), on HTTP calls and OTLP export alike; it
  warns once when the key would go over plain `http://` to a non-loopback host;
- a plain OpenTelemetry exporter uses
  `OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <key>"`;
- the dashboard asks for a `read` or `admin` key once and exchanges it for a session cookie
  (`HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS, `OPENGRADE_UI_SESSION_HOURS`, default 12).
  The cookie holds the key id, an expiry and an HMAC signed with the env key, never a key; it is
  not a user login.

### Per-client keys and scopes

Create one key per app, CI job or person in the dashboard (**Settings**) or with
`opengrade keys create`. Keys look like `og_…`; the server stores only their SHA-256 and shows
the key once. Each key has a name and one scope:

| Scope | Can | Cannot | For |
|---|---|---|---|
| `ingest` | `POST /v1/traces`, `POST /api/v1/projects/{id}/trace-scores`, `POST /api/v1/projects/{id}/live-interactions`, `GET /api/v1/projects` (slug lookup) | read data, change anything else, open the dashboard | apps in production |
| `read` | every read-only request (`GET`), the dashboard | any write (incl. reviews, release check, alert preview), send traces, manage keys | people who only look |
| `admin` | everything, incl. managing keys | — | CI (`opengrade evaluate` / `check`), administrators |

Revoking a key rejects it at once (within 30 s when revoked from the CLI in another process) and
ends the dashboard sessions opened with it. `last_used_at` shows which keys are still in use.

**Rotating the env key:** set the new value in `OPENGRADE_API_KEY` and restart. Dashboard
sessions are signed with the env key, so they end when that key changes. Per-client keys are
not affected. Move clients to the new key before or immediately after the restart.

There are **no user accounts**. If you need per-person audit, give each person a `read` or `admin` key with their name. With auth on, that key name is written server-side to `trace_scores.author` and `live_score_reviews.reviewer` (client-supplied values are ignored).

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
   Judge `LLM_API_KEY` stays in the process environment / cwd `.env` (writable from
   **Settings → LLM judges**). It is never written to the application database so DB
   dumps and backups do not contain the provider key. Non-secret LLM knobs may live in
   the `system_llm_settings` overlay (single API replica; in-process cache only).
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

Input/output content is captured by default (live scoring and the response view need it); turn it off as described below.

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

`@og.trace` records arguments and the return value as `input.value` / `output.value`. Turn capture off entirely where a function handles secrets or personal data, so the text never leaves the process:

```python
@og.trace(capture_input=False, capture_output=False)
def lookup_customer(customer_id: str, api_key: str) -> dict: ...
```

`capture_input=False` / `capture_output=False` remain the hard local off-switch on each decorated function.

When you still need structure in traces but must scrub values, use global hooks and optional per-decorator overrides. Decorator `redact` / `redact_output` replace the global callback for that function; pass `None` on the decorator to inherit the global. There is no built-in key denylist—your callbacks decide what to change.

```python
og.configure_capture(
    redact=lambda name, value: "***" if name == "api_key" else value,
    redact_output=lambda value: {"ok": True},
)

@og.trace(
    redact=lambda name, value: value if name != "ssn" else "<redacted>",
    redact_output=lambda value: {"ok": True},
)
def lookup(customer_id: str, api_key: str) -> dict: ...
```

Automatic `input.value` from `@og.trace` is a flat JSON object mapping **bound parameter names** to values (not `{"args": [...], "kwargs": {...}}`). Bound names come from the function signature; `self` and `cls` are omitted. Redactors run before serialization; failures become the string `"<redact error>"` and never raise into your application code. Manual `og.set_input()` / `set_output()` on a span are not passed through these hooks (only the automatic capture path).

`OPENGRADE_DISABLED=1` disables the SDK entirely (no spans, scores or feedback are sent).

Spans emitted by auto-instrumentation (OpenInference instrumentors for OpenAI, LangChain, LlamaIndex, …) follow their own settings; use the server switch above to guarantee nothing is stored.

### Not yet available

- Retention/TTL for stored traces.

Until then, use the two switches above, or put a redacting OpenTelemetry Collector processor in front of `/v1/traces`.

## Future (optional platform overlays)

These remain optional and should not reshape the domain core:

- reverse-proxy identity header
- workspace RBAC
- SSO/OIDC
- encryption-at-rest documentation
- audit logs
- configurable retention
