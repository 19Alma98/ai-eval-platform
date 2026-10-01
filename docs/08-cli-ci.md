# CLI and CI/CD

## CLI

Package: `aiobs-cli` (repo `cli/`), console script `aiobs`.

Implementation:
- Typer
- httpx
- Rich
- PyYAML

Phase 4 command:

```text
aiobs check --policy aiobs.yaml [--base-url URL] [--project-id ID] [--experiment-id ID] [--baseline-experiment-id ID]
```

YAML may include meta fields (`api_base_url`, `project_id`, `experiment_id`, `baseline_experiment_id`) plus policy blocks. Flags override meta fields. The CLI strips meta keys and POSTs the remainder as `policy` to `POST /api/v1/projects/{project_id}/release-check`.

Planned later (not Phase 4):

```text
aiobs init
aiobs projects
aiobs traces list
aiobs traces show
aiobs dataset create
aiobs dataset add
aiobs experiment run
aiobs experiment compare
```

`aiobs login` is not required for v0.1. The CLI talks to a local/self-hosted API on a trusted network. An optional API-key flag may be added later without becoming an MVP dependency.

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
