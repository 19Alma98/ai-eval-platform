# Changelog

All notable changes to OpenGrade are documented here. The two packages, `opengrade-ai` (SDK + CLI)
and `opengrade-ai-server` (API + UI), are released together with the same version.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). While the version is `0.x`, minor releases may contain
breaking changes; they are listed under **Changed** with a migration note.

## [Unreleased]

### Added

- **SDK 0.2.0 — multi-instance runtime:** `Opengrade` settings handle, `opengrade.current()`, and
  `with og.activate():` / `with og:` for per-scope clients and tracing in one process.
- **SDK 0.2.0 — bound control plane:** `Client(..., project_id=...)` and `og.client` require an
  explicit project; no process-wide `project_id` fallback.
- **SDK 0.2.0 — OTLP routing:** per-instance export via `_RoutingSpanProcessor` on the shared
  `TracerProvider` (`Opengrade.init_tracing()` / `init()` on the active instance).
- Example: multi-tenant FastAPI (`examples/fastapi_multi_tenant/`) activating one `Opengrade` per
  request.
- Monitoring/Overview: custom absolute time range, IANA timezone picker (display only), and
  compare-to-previous-period overlay on monitoring charts.
- Monitoring drill-down: chart bucket clicks and local metric-alarm banners open Traces with
  `since`/`until` (and `status=error` for error bars); KPI Traces link keeps the current window.
- Live answers: load more (`offset` / `next_offset`), optional time range + metadata filters,
  SDK metrics and feedback chips in the Scores column; Overview/Monitoring/Traces auto-refresh
  every 30s.
- OTLP head sampling (`OTLP_TRACE_SAMPLE_RATE`) and span attribute size limits
  (`OTLP_MAX_SPAN_ATTR_CHARS`); SDK `init(trace_sample_rate=..., max_capture_bytes=...)` /
  `OPENGRADE_TRACE_SAMPLE_RATE` / `OPENGRADE_MAX_CAPTURE_BYTES`.
- Read-only dashboard for `read` API key sessions: write buttons are hidden (`useCanWrite`).
- With auth on, `trace_scores.author` and `live_score_reviews.reviewer` are set from the API key
  name (client-supplied values ignored).
- Experiment aliases: Baseline badge for `main`, promote / manage / history on the experiments
  list and compare baseline card (detail already had them).
- Experiments list: test-set version in the Test set column, URL filter `?dataset=`, and per-metric
  mean columns from experiment summaries.
- `opengrade --version` (`-V`) prints the installed `opengrade-ai` and `opengrade-ai-server`
  versions; it works with the SDK alone too.
- `ExperimentResult.summary()` explains metrics that were skipped on some test cases (for example
  `must_contain` without a `must_contain` list on the item) instead of showing a bare `-`.
- Failed API-key attempts are rate-limited per client IP (`OPENGRADE_AUTH_FAILED_ATTEMPTS_PER_MINUTE`,
  default 60; lockout via `OPENGRADE_AUTH_FAILED_LOCKOUT_SECONDS`). Over the limit returns `429`
  with `Retry-After`.
- List APIs for projects / datasets / experiments / metrics-sets accept optional `name`/`slug`
  filters and `limit`/`offset`. The SDK passes them through; `set_project` / `evaluate` resolve by
  filtered list instead of scanning everything.
- Live runs URL sync: `?failed=1`, `?waiting=1`, `?q=`; experiment matrix sort via `?sort=` / `?order=`.

### Changed

- `opengrade ui` startup banner says "OpenGrade UI" (was "AI Eval UI").
- PyPI "Documentation" link points to the docs site.
- Live interactions list batches score and review loads (one query each per page, not per row).
- Compare treats missing `prompt_version` / `judge_model` / `config_hash` as their own identity
  (a recorded value vs missing is a config mismatch).
- `TimeRangePicker` takes only `window` / `onWindowChange` (no preset-only props or shared
  time-range context).

### Removed

- `OPENGRADE_API_KEY_PREVIOUS` / `api_key_previous` (env key rotation overlap).
- Process-wide `project_id` fallback on `Client` / `AsyncClient` (pass `project_id` explicitly).
- Docs: the completed MVP planning pages (MVP user stories, definition of done).
- SQLite startup stamp for pre-Alembic `create_all` databases (delete a stale local DB instead).
- Standalone `AppConfigClient(...)` construction; use `Client(...).app_configs` /
  `opengrade.get_client().app_configs`.
- `opengrade.MAX_CAPTURE_BYTES` alias; use `DEFAULT_MAX_CAPTURE_BYTES` or `max_capture_bytes()`.
- `@opengrade.trace_async`; use `@opengrade.trace` for sync and async functions.

## [0.1.1] - 2026-11-04

### Added

**Evaluation and experiments (SDK)**

- `opengrade.sweep(...)`: one experiment per configuration of a grid (models, prompts, chunk
  sizes…), ranked in a leaderboard.
- `opengrade.evaluate_retrieval(...)`: score only the retriever (hit@k, recall@k, MRR, optional
  context judges) without generating an answer.
- `evaluate(repeats=N)`: run each item N times, average the scores per item and report flaky items.
- `evaluate(group_by="field")`: means and baseline deltas per metadata value, also in the summary,
  compare and release gate.
- Experiment aliases (`alias:main`): a passing gate can promote the run as the new baseline
  (`opengrade evaluate --promote main`, `client.experiments.set_alias`). The UI shows and manages
  aliases.
- Each experiment records the git revision (commit, branch, dirty state) of the code under test,
  shown in compare.
- Custom LLM judges, plus built-in **citation accuracy** and **correct refusal** judges for RAG.
- `rag_qa` datasets accept unanswerable items (expected refusal).

**Tracing (SDK)**

- `with opengrade.span(name, kind=...)` (and `async with`) to trace a block inside a function.
- `opengrade.set_user`, `set_session`, `set_tags`, `set_metadata` and `using_attributes(...)`; the
  UI and API filter traces by tag, user, session and metadata.

**CI quality gate (`opengrade evaluate` / `opengrade check`)**

- `--require-baseline`: fail instead of silently skipping the comparison when there is no baseline.
- Relative bounds vs the baseline for latency, cost and run-level metrics (`max_increase_pct`, …).
- Item-level checks: `regression.max_new_failures` (test cases that pass on the baseline must not
  fail) and must-pass **critical** test cases.
- Statistical power warning (`max_detectable_delta`) and a **non-inferiority** check
  (`regression.non_inferiority_margin`).
- The CLI lists the test cases that got worse than the baseline.
- Markdown (`--report-md`, for job summaries / PR comments) and JUnit (`--junit`) reports.
- The UI release page and the CLI use the same comparison logic.
- Runnable examples: `examples/ci_regression_gate`, `examples/llm_regression_gate`,
  `examples/non_inferiority_gate`.

**Production monitoring (server + UI)**

- Server-side alert rules with webhook notifications, including drift and anomaly conditions.
- Filter and compare production traffic by release version and environment.
- Retention of production data per project, with a server-wide default.
- Configurable experiment charts.

**Security**

- API key authentication: set `OPENGRADE_API_KEY` on the server (bootstrap admin key), then create
  per-client keys with `admin` / `read` / `ingest` scopes in **Settings → API keys** or with
  `opengrade keys create`. The SDK sends `OPENGRADE_API_KEY` as `Authorization: Bearer`.
- When content capture is off, flattened LLM content and document text are redacted too.

**Server operations**

- Alembic migrations ship inside the `opengrade-ai-server` wheel and run on startup (also for
  `opengrade ui --backend-store-uri postgresql+asyncpg://…`), under a Postgres advisory lock.
- `/ready` readiness probe (database check), `X-Request-ID` on every request.
- OTLP ingest backpressure: `429` / `503` with `Retry-After` above the configured rate, in-flight or
  pending-score limits.
- SQLite in WAL mode with `busy_timeout`; graceful shutdown drains running scorings.
- `opengrade ui` fails fast when the port is already taken and prints the judge / content-capture
  settings at startup.

**Docs and examples**

- [Getting started in 15 minutes](docs/getting-started.md) with seed scripts, screenshots and a
  README walkthrough GIF.
- `examples/sdk_tour`: a guided, offline `uv` project covering tracing, RAG verification, model
  comparison, custom metrics and alerts.
- `scripts/smoke_install.py` and the *Install smoke* workflow: clean-install test of the built
  wheels (or of a PyPI release) on Linux, macOS and Windows.

### Changed

- **Content capture is on by default** (`CONTENT_CAPTURE_ENABLED=true`): span inputs/outputs are
  stored. Set it to `false` to keep only structure, timings and metrics.
- Frontend redesign: verdict-first overview, a single Production section, report-card visuals,
  mobile layout and accessibility fixes, side panels instead of modals.
- Package metadata: license (Apache-2.0), authors, project URLs and classifiers; `py.typed` in the
  SDK wheel; development tools moved to `[dependency-groups]`.

### Fixed

- The SDK never breaks the host application: `init()` attaches to an existing OpenTelemetry
  `TracerProvider` instead of replacing it; `@trace` supports sync, async, generator and async
  generator functions; OTLP batches are gzip-compressed and split on failure; transport errors are
  wrapped in `OpengradeError` / `OpengradeConnectionError`; one HTTP client per event loop.
- `init(project_id=…/project_slug=…)` is honored by `resolve_project_id`.
- Inline datasets interrupted half-way are resumed instead of reused incomplete.
- `finish()` no longer fails after the task work on large outputs or NaN/inf scores.
- Atomic scoring of experiments and live interactions; JSON with NUL bytes is rejected.
- SQLite: duplicate metrics set (409) and silenced server logs.
- Alembic root resolution for editable and Docker layouts.

### Removed

- `examples/otlp_hello` (use `examples/sdk_hello` or the SDK tour).
- Orphan smoke scripts.

## [0.1.0] - 2026-10-15

First public release on PyPI of `opengrade-ai` and `opengrade-ai-server`: OTLP / OpenInference
trace ingest, datasets (test sets), metrics packs with deterministic metrics and LLM judges
(LiteLLM), experiments with baseline compare, `opengrade ui` (SQLite + packaged UI),
`opengrade check` quality gate with exit codes for CI, Docker Compose stack with Postgres.

[Unreleased]: https://github.com/19Alma98/ai-eval-platform/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/19Alma98/ai-eval-platform/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/19Alma98/ai-eval-platform/releases/tag/v0.1.0
