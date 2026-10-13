# CLI and CI/CD

## CLI

The `aiobs` console script ships with the SDK (**`aiobs-eval`**, `aiobs.cli:main`) and delegates to the server CLI (`aiobs_server.cli`, repo `backend/`). Without the server installed, `aiobs` exits 1 and prints `pip install "aiobs-eval[ui]"`. The server also exposes the same commands as `aiobs-server`, and depends on `aiobs-eval`, so `pip install aiobs-eval-server` provides `aiobs` too.

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

## Publishing to PyPI

Workflow: [`.github/workflows/publish.yml`](../.github/workflows/publish.yml).

Distributions:

| PyPI name | Import / CLI |
|-----------|--------------|
| `aiobs-eval` | `import aiobs` / console script `aiobs` |
| `aiobs-eval-server` | `aiobs_server` / console script `aiobs-server` |

### One-time setup (Trusted Publishing)

1. Create a GitHub Environment named **`pypi`** on `19Alma98/ai-eval-platform` (optional protection rules / required reviewers).
2. On [PyPI](https://pypi.org/manage/account/publishing/): for **each** of `aiobs-eval` and `aiobs-eval-server`, add a **pending** trusted publisher:
   - Owner: `19Alma98`
   - Repository: `ai-eval-platform`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. No API tokens are required.

### Release steps

The git tag is the only source of the version. Both packages read it through [hatch-vcs](https://github.com/ofek/hatch-vcs); `aiobs.__version__`, `aiobs_server.__version__` and the API's OpenAPI version read the installed package metadata. Untagged builds get a dev version such as `0.1.1.dev3+g1a2b3c4`.

1. Tag the commit and push the tag: `git tag v0.1.0 && git push origin v0.1.0`
2. The workflow builds the UI (`package-ui.sh`) and both wheels with `AIOBS_RELEASE_BUILD=1`. That makes each package's `hatch_build.py` pin its sibling to the same version: the server needs `aiobs-eval==X`, and `aiobs-eval[ui]` needs `aiobs-eval-server==X`. Dev builds leave those requirements unpinned so `uv.lock` stays stable.
3. The workflow checks that both wheels carry the tag's version and the exact pins, and that `_ui/index.html` is inside the server wheel. Then it uploads via OIDC.

Dry-run (build only, no upload): Actions → **Publish** → Run workflow → leave **dry_run** checked.

Install for users after publish:

```bash
pip install 'aiobs-eval[ui]'
aiobs ui
```

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
