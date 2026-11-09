# Phase 3 report: Client / AsyncClient bound `project_id`

## Status

Complete.

## Changes

- Added `_client_resolve.resolve_bound_project()` (explicit > client-bound > global with one-time `DeprecationWarning`).
- `Client` / `AsyncClient` accept optional `project_id`; resources take a `ProjectResolver` and call `self._project(...)`.
- `get_client()` / shared `AsyncClient` instances pass `project_id` from runtime settings or active project when the client is first created.
- Replaced direct `resolve_project_id` in resources, `experiment._resolve_project`, `judges`, `feedback._queue`, and `_production.after_call` (via `get_client()._project(None)`).
- Tests in `test_client.py` for bound client isolation, two clients, and deprecation fallback.

## Verification

- Focused brief suite: **60 passed**
- Full SDK suite: **392 passed, 2 skipped**

## Self-review

- Shared client captures `project_id` at first `get_client()`; later `set_project()` does not rebind the client (global fallback + warning still works).
- Legacy tests that assign `_context._CLIENT` without `project_id` now emit expected `DeprecationWarning` on resource calls.
- `AppConfigClient` unchanged (no project-scoped routes in current API).

## Concerns / follow-ups

- Phase 4 may want to refresh shared client project binding on `set_project` / `init` to reduce deprecation noise.
- Consider filtering or updating `test_context` cases to use `project_id=` on hand-built clients where the test is not about global fallback.
