# CLI and CI/CD

## CLI

Package name: `aiobs`.

Implementation:
- Typer
- httpx
- Rich

Commands:

```text
aiobs init
aiobs projects
aiobs traces list
aiobs traces show
aiobs dataset create
aiobs dataset add
aiobs experiment run
aiobs experiment compare
aiobs check
```

`aiobs login` is not required for v0.1. The CLI talks to a local/self-hosted API on a trusted network. An optional API-key flag may be added later without becoming an MVP dependency.

## CI integration

Example:

```yaml
- name: Run AI evaluation gate
  run: |
    aiobs experiment run support-regression
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
