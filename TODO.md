# TODO

Open items only. Completed items from the RAG evaluation reviews (2026-10-08, 2026-10-11) and the
PyPI-readiness review (2026-10-15) were removed; they are in git history.
Priority: **P0** blocks a public release, **P1** fix before promoting it, **P2** polish / gaps.

## Release / product

### Server / container production-readiness — P1

- [ ] Multi-replica unsafe: startup recovery on one replica fails/requeues other replicas' running
  work. Needs leases or leader election (ties into "Pluggable job queue").
  **Supported mode: single API replica.** Scaling replicas without a job queue is unsafe.

### Product gaps vs MLflow / Langfuse — P2

- [ ] **Auth follow-ups** (API keys with `admin` / `read` / `ingest` scopes shipped; no user
  accounts by design, see `docs/10-security-privacy.md#api-keys`):
  - Optional project binding for `ingest` keys (`project_id` on the key, enforced on OTLP
    `X-Project-Id` / `X-Project-Slug` and the project routes).
- [ ] Live view still open: session/user grouping; filter by SDK metric / feedback name (Scores
  column, load more, time-range/metadata filters, and auto-refresh on Overview/Monitoring/Traces
  shipped).
- [ ] Drill-down from server alert rules / webhook events to the traces that caused them (chart
  points and local metric-alarm banners already deep-link).
- [ ] Retention/TTL and per-project quotas (see "OTLP high volume" below).

### Monitoring gaps (2026-11 review) — P2

- [ ] **Online evaluation rules**: run a judge or evaluator on a sampled subset of traces matching a
  filter (name, environment, attribute), not only on RAG question/answer live interactions.
- [ ] **Span-attribute metrics**: aggregate a numeric span attribute as a time series and allow it in
  alert rules (`ALERT_METRICS` is a fixed list).
- [ ] **Trace-structure checks**: assertions on span order / counts / errors (retriever before LLM,
  max N tool calls), agent trajectory evaluation beyond `tool_call_success`.
- [ ] **RAG answer checks still open** (citation accuracy, correct refusal and safety checks shipped
  as `citation_accuracy` / `refusal` / `pii` / `toxicity` / `prompt_injection`): Cohen's kappa for
  judge-vs-human agreement per judge (today only % agreement); deterministic `patterns` method for
  PII; per-category severity / thresholds for the safety checks.
- [ ] **Scheduled canary runs** of a gold subset against the live endpoint, alert on change.

### Conversational RAG (multi-turn) — P2

Today the unit of evaluation is one question/answer pair; here it is the conversation. Order:
offline first (1-2, builds on dataset → experiment → compare), then the production view (3),
reusing the same judges.

- [x] **1. Multi-turn datasets**: task type `rag_chat`; an item holds the chat history (list of
  `{role, content}` turns) plus the final user question; `expected_output` is the reference for the
  last turn. CSV/JSONL import and `og.evaluate` pass the history to the task
  (`item.input` = `{"history": [...], "question": "..."}`; helper `opengrade.chat_input`).
- [x] **2. Conversation judges**:
  - query rewriting: `query_rewrite_faithfulness` + `opengrade.set_search_query` /
    `opengrade.retrieval.query`;
  - consistency with earlier turns: `conversation_consistency`;
  - conversation-level metrics: `resolution` (label + `turns_to_resolution`);
  - existing judges (`groundedness`, `citation_accuracy`, `refusal`, …) keep scoring the last turn
    via `resolve_rag_question` / `prompts.question_text`.
- [x] **3. "Conversations" section (UI + production)**: Production tab groups traces by `session.id`,
  chat timeline + session judge run / idle sampler; promote session → `rag_chat` dataset item.
  Session-level alert rules remain a follow-up.

## Deferred

Do not block feature work. Pick these up when the trigger below each item shows up
(or an operator explicitly needs the flexibility).

### Performance

Live-list score/review N+1 is batched (one scores query + one reviews query per page).
Next: `failed_only` denormalization (batching alone does not remove O(N) failed_only scans).

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

