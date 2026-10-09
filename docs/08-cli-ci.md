# CLI and CI/CD

## CLI

Package: **`aiobs-server`** (repo `backend/`), console script `aiobs`.

Implementation:
- Typer
- httpx2
- Rich
- PyYAML
- uvicorn (for `aiobs ui`)

### Local UI

```text
aiobs ui [--host 127.0.0.1] [--port 8000] [--backend-store-uri URI] [--open/--no-open]
```

Defaults to SQLite at `sqlite+aiosqlite:///./aiobs.db`. Override with `--backend-store-uri` or `DATABASE_URL` for Postgres. Requires a packaged UI (`./scripts/package-ui.sh` or a release wheel).

### Release gate

```text
aiobs check --policy aiobs.yaml [--base-url URL] [--project-id ID] [--experiment-id ID] [--baseline-experiment-id ID]
```

YAML may include meta fields (`api_base_url`, `project_id`, `experiment_id`, `baseline_experiment_id`) plus policy blocks. Flags override meta fields. The CLI strips meta keys and POSTs the remainder as `policy` to `POST /api/v1/projects/{project_id}/release-check`.

Planned later:

```text
aiobs init
aiobs projects
aiobs traces list
aiobs experiment compare
```

`aiobs login` is not required for v0.1. The CLI talks to a local/self-hosted API on a trusted network.

## CI integration

See `.github/workflows/release-gate.yml.example` and `examples/aiobs.yaml`.

Example:

```yaml
- name: Run AI evaluation gate
  run: |
    # Assume experiment evaluation already completed against the API
    aiobs check --policy aiobs.yaml
```

Exit codes:
- 0 = pass
- 1 = quality gate failed
- 2 = configuration error
- 3 = infrastructure/evaluation execution error

## GitHub integration — later

Create a GitHub Check Run or PR comment:

```text
AI Quality Gate

✓ Answer quality   0.91 >= 0.85
✓ Groundedness     0.92 >= 0.90
✗ P95 latency      2.61s > 2.00s

Result: FAILED
```

## Benchmarking

CLI should optionally emit:
- samples/sec
- evaluator duration
- total tokens
- estimated cost
- failure count
