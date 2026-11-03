# TODO

Open items only. Completed items from the RAG evaluation reviews (2026-10-08, 2026-10-11) and the
PyPI-readiness review (2026-10-15) were removed; they are in git history.
Priority: **P0** blocks a public release, **P1** fix before promoting it, **P2** polish / gaps.

## Release / product

### Packaging / release — P0

- [ ] **Migrations not shipped / not run outside Docker** (`infrastructure/db.py:85`,
  `pyproject.toml` packages only `src/opengrade_server`). `opengrade ui --backend-store-uri
  postgresql+asyncpg://…` on an empty DB → 500 on every write. Fix: package Alembic inside
  `opengrade_server`, run `upgrade head` programmatically on startup under an advisory lock. (confirmed)
- [ ] **Docker image not published** (`publish.yml` only does PyPI). Publish to GHCR/Docker Hub on tag,
  non-root user, documented env vars.

### Server / container production-readiness — P1

- [ ] Multi-replica unsafe: startup recovery on one replica fails/requeues other replicas' running
  work. Needs leases or leader election (ties into "Pluggable job queue").
  **Supported mode: single API replica.** Scaling replicas without a job queue is unsafe.

### Product gaps vs MLflow / Langfuse — P2

- [ ] **Auth**: API keys in SDK + server — needed before any non-localhost container deployment
  (see also "Optional auth" below). Design decided 2026-11-03:
  - **No users.** API keys only; no accounts, passwords or roles. SSO, if ever needed, goes in a
    reverse proxy in front (oauth2-proxy, Cloudflare Access). Users only if per-person permissions,
    multi-tenant or verified audit become goals; a key can then belong to a user.
  - **Scopes:** `admin` (everything, incl. key management, deletes, experiments, CI
    `opengrade evaluate`), `read` (dashboard + every `GET`; no writes at all, not even reviews),
    `ingest` (only `POST /v1/traces`, `POST /api/v1/trace-scores`,
    `POST /api/v1/projects/{id}/live-interactions`; cannot open the UI). `ingest` is the key that
    lives in production apps.
  - **Phase 1 — done:** `OPENGRADE_API_KEY` = the `admin` key (+ `OPENGRADE_API_KEY_PREVIOUS` for
    rotation), bearer on HTTP + OTLP in the SDK, API key prompt in the UI (not a user login:
    key → `HttpOnly` HMAC session cookie). See `docs/10-security-privacy.md#api-key`.
  - **Phase 2:** `api_keys` table in the server's own DB (no separate cloud auth service): name,
    optional `project_id` (an `ingest` key bound to a project needs no slug lookup), `scope`,
    `prefix`, SHA-256 `key_hash` only, `created_at`, `last_used_at`, `revoked_at`. Settings → API
    keys page (key shown once, revoke, last used) + `opengrade keys create`. The env key stays as
    the bootstrap admin key. Key name fills `trace_scores.author` / `live_score_reviews.reviewer`
    server-side.
- [ ] **PII redaction**: capture currently grabs every argument incl. `self`/secrets. Per-arg
  include/exclude, redaction hook, global capture switch.
- [ ] **Sampling** (head sampling) and configurable span size limits.
- [ ] `AsyncClient` parity (datasets, experiments), `aevaluate`.
- [ ] Pagination on SDK list calls; `set_project` / `evaluate` scan all projects/datasets/experiments.
- [ ] Experiments list: dataset-version column/filter and metric columns (the Compare-all charts
  already plot any metric over time).
- [ ] Synthetic test-set generation from a document corpus.
- [ ] Experiment aliases in the UI: "baseline" badge on the experiment an alias points to, promote /
  roll back buttons, alias history (API + CLI `--promote` already shipped, `/experiment-aliases`).
- [ ] Live view: session/user grouping, filter by SDK metric / feedback, SDK metrics + feedback in the
  list Scores column, "load more" beyond 50, time-range/metadata filters, auto-refresh on
  Overview/Monitoring/Traces.
- [ ] Drill-down from alarms / chart points to the traces that caused them.
- [ ] Filters persisted in the URL (live-runs, matrix rows; the trace list already keeps its
  tag / metadata / user / session filters there); CSV/JSON export.
- [ ] Trace attribute index covers traces ingested after migration `0024_trace_tags` only; older
  traces keep their `user_id` / `session_id` filters but not tag / metadata ones (no backfill).
- [ ] Session view: one page per `session_id` showing the conversation turn by turn.
- [ ] Retention/TTL and per-project quotas (see "OTLP high volume" below).
- [ ] Custom time range / timezone and compare-to-previous-period on monitoring.

### Monitoring gaps (2026-11 review) — P2

- [ ] **Online evaluation rules**: run a judge or evaluator on a sampled subset of traces matching a
  filter (name, environment, attribute), not only on RAG question/answer live interactions.
- [ ] **Span-attribute metrics**: aggregate a numeric span attribute as a time series and allow it in
  alert rules (`ALERT_METRICS` is a fixed list).
- [ ] **Trace-structure checks**: assertions on span order / counts / errors (retriever before LLM,
  max N tool calls), agent trajectory evaluation beyond `tool_call_success`.
- [ ] **RAG answer checks still open** (citation accuracy and correct refusal shipped as
  `citation_accuracy` / `refusal`): safety checks (PII in the output, toxicity, prompt injection in
  retrieved documents); judge-vs-human agreement (kappa / % agreement) shown per judge.
- [ ] **Scheduled canary runs** of a gold subset against the live endpoint, alert on change.

### Conversational RAG (multi-turn) — P2

Today the unit of evaluation is one question/answer pair; here it is the conversation. Order:
offline first (1-2, builds on dataset → experiment → compare), then the production view (3),
reusing the same judges.

- [ ] **1. Multi-turn datasets**: task type `rag_chat`; an item holds the chat history (list of
  `{role, content}` turns) plus the final user question; `expected_output` is the reference for the
  last turn. CSV/JSONL import and `opengrade.evaluate` pass the history to the task
  (`item.input` = `{"history": [...], "question": "..."}` or a dedicated `item.history`).
- [ ] **2. Conversation judges**:
  - query rewriting: the standalone/search query the app built is faithful to what the user means
    given the history (needs the rewritten query recorded, e.g. on the RETRIEVER span or via an SDK
    helper);
  - consistency with earlier turns: no contradiction of what the assistant already said, no
    forgotten constraints the user gave;
  - conversation-level metrics: resolved or not, turns to resolution;
  - existing judges (`groundedness`, `citation_accuracy`, `refusal`, …) keep scoring the last turn.
- [ ] **3. "Conversations" section (UI + production)**: SDK `opengrade.set_session()` /
  `set_user()` (the server already ingests `session.id` / `user.id` but nothing uses them), a view
  that groups traces by session as a chat timeline, conversation judges run on the whole session
  (sampled, after a session goes idle), session-level filters and alerts.

## Deferred

Do not block feature work. Pick these up when the trigger below each item shows up
(or an operator explicitly needs the flexibility).

### Performance

When optimizing, do N+1 batching first, then `failed_only` denormalization
(batching alone does not remove O(N) failed_only scans).

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row (~3 queries ×
  page size; default 50, polled every 5s). Batch-load scores and reviews for a page.
  Fix when: list feels slow or query volume / pool wait shows up under normal browsing.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL. Fix when: thousands+ interactions and the filter is used often (or empty full scans hurt).
  Do not replace with a fixed recent window — older failures must still surface.
  Trace scores now add one `list_by_trace_ids` query per *scanned* page; the denormalized verdict
  must also account for trace-score FAILs (they can arrive after the interaction).

### Production / ops

Postgres is source of truth for job state; the queue is a deployment detail. No Redis
(or other broker) in Compose or core deps — operators bring their own if they want one.

- [ ] **Pluggable job queue.** Routes/OTLP/recovery must not call FastAPI
  `BackgroundTasks` directly; call a `JobQueue.enqueue(name, payload)` port.
  Default backend: in-process (current BackgroundTasks behavior). Stable
  idempotent runners (`run_live_score`, `run_experiment_score`, …) stay the
  execution API. Optional later: Postgres `SKIP LOCKED` + `opengrade worker`,
  Redis/SQS/etc. as extras or docs (“bring your broker”), or a hook so operators
  push to their own orchestrator. Fix when: restarts drop work under load, API
  latency suffers from in-process judges, or multi-replica API needs shared queue.
- [ ] **OTLP high volume.** Batch writes and retention/TTL for traces/spans.
  Fix when: continuous production OTLP, disk growth, or ingest/query pressure.
  ClickHouse / object storage only if benchmarks justify (roadmap Phase 7).

### Auth

Trusted-network / reverse-proxy remains the default self-hosted model.

- [ ] **Optional auth.** Opt-in API key / basic auth for `/api/v1/*` and `/v1/traces`
  when someone wants app-level protection without an edge layer. Not required for
  the trusted-network model. Fix when: an operator asks for app-level auth (SSO/RBAC
  stay out of scope unless the product later owns identity).

### Platform

Floor stays `requires-python = ">=3.12"` (CI/mypy pinned to 3.12). Do not raise
the minimum just because a newer CPython shipped.

- [ ] **Python version bump.** Optionally CI-matrix-test on 3.13/3.14; raise the
  floor only if a dependency drops 3.12 or we need language features that justify
  cutting older envs. 3.15 (2026-10) is too new for a floor bump. Fix when:
  deps force it, or we deliberately want newer typing/runtime and accept the
  support cut.

