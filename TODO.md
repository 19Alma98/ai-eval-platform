# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

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
  execution API. Optional later: Postgres `SKIP LOCKED` + `aiobs worker`,
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


## Other

- Nome su PyPI
