# Phase 5 report: per-instance OTel routing

## Summary

Implemented shared-process `TracerProvider` with `_RoutingSpanProcessor` so each `Opengrade` instance exports via its own `BatchSpanProcessor`/exporter (per-request OTLP `X-Project-Id` headers). Module `opengrade.init()` delegates to `init_for_instance` on the default handle.

## Changes

- **`_otel.py`**: `_RoutingSpanProcessor`, `init_for_instance`, per-instance registration, release attrs on router `on_start`, WeakSet atexit teardown, instrumentor single-owner warning.
- **`_opengrade.py`**: stable `_instance_id`, `init_tracing` → `init_for_instance`, `__weakref__` slot.
- **`experiment.py`**: trace binding flush gated on `current().tracing_enabled`.
- **`test_otel_routing.py`**: isolation, asyncio, host provider, instrumentor warning.

## Verification

```bash
cd sdk && uv run pytest -q
# 401 passed, 2 skipped
```

## Notes

- Test hook `_span_exporter=` for `InMemorySpanExporter` in routing tests.
- Host-provider attach preserves ownership flags on force re-init; release metadata stamped via router (not only export chain).

## Commit

Phase 5 commit on `feature/sdk-eliminate-global-state` (not pushed).
