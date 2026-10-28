# CLI and CI/CD

## CLI

The `opengrade` console script ships with the SDK (**`opengrade-ai`**, `opengrade.cli:main`) and delegates to the server CLI (`opengrade_server.cli`, repo `backend/`). Without the server installed, `opengrade` exits 1 and prints `pip install "opengrade-ai[ui]"`. The server also exposes the same commands as `opengrade-server`, and depends on `opengrade-ai`, so `pip install opengrade-ai-server` provides `opengrade` too.

Implementation:
- Typer
- httpx2
- Rich
- PyYAML
- uvicorn (for `opengrade ui`)

### Local UI

```text
opengrade ui [--host 127.0.0.1] [--port 8000] [--backend-store-uri URI] [--open/--no-open]
```

Defaults to SQLite at `sqlite+aiosqlite:///./opengrade.db`. Override with `--backend-store-uri` or `DATABASE_URL` for Postgres. Requires a packaged UI (`python scripts/package_ui.py`, `./scripts/package-ui.sh`, or a release wheel; Node.js >= 22 to build from a clone).

Loads `.env` from the process working directory when present (Pydantic Settings) and prints judge model / API key presence / `LLM_API_BASE` / content-capture at startup. Exits with code `2` if the bind port already accepts connections (e.g. Docker on `:8000`) — stop the other process or pass `--port`.

### Evaluate (exam + optional gate)

```text
opengrade evaluate --config opengrade.yaml [flags…]
```

`--policy` is an alias for the same YAML path. Runs the gold exam (dataset + metrics + task), then applies policy blocks via release-check when present.

| Mode | When |
|------|------|
| Embedded | No `api_base_url` / `--base-url` → temp SQLite + in-process API (pytest-like CI) |
| Remote | `api_base_url` or `--base-url` set |

Exam definition (XOR):

- **`from_experiment`** (preferred): clone `dataset_id` + `metrics_set_id` from an existing experiment; baseline defaults to that id.
- **Bootstrap:** `dataset` + `metrics` (path/name + kinds) for the first exam / embedded.

Task wiring (XOR): `--task module.path:callable` or `--script path.py` (must define `task(item)`; optional `DATASET` / `METRICS` for bootstrap).

Judge secrets: `evaluate.judge.api_key_env: LLM_API_KEY` reads the environment (set via CI secrets). Do not commit API keys in YAML.

Flags override YAML: `--task`, `--script`, `--dataset`, `--metrics`, `--name`, `--baseline`, `--from-experiment`, `--base-url`, `--project`, `--backend-store-uri`, `--json`.

Design: [`docs/superpowers/specs/2026-10-28-opengrade-evaluate-cli-design.md`](superpowers/specs/2026-10-28-opengrade-evaluate-cli-design.md).

### Quality gate only

```text
opengrade check --policy opengrade.yaml [--base-url URL] [--project-id ID] [--experiment-id ID] [--baseline-experiment-id ID]
```

YAML may include meta fields (`api_base_url`, `project` / `project_id`, `experiment_id`, `baseline_experiment_id`) plus policy blocks. The `evaluate:` block is ignored. Flags override meta fields. The CLI strips reserved keys and POSTs the remainder as `policy` to `POST /api/v1/projects/{project_id}/release-check`.

Planned later:

```text
opengrade init
opengrade projects
opengrade traces list
opengrade experiment compare
```

`opengrade login` is not required for v0.1. The CLI talks to a local/self-hosted API on a trusted network.

## Publishing to PyPI

Workflow: [`.github/workflows/publish.yml`](../.github/workflows/publish.yml).

Distributions:

| PyPI name | Import / CLI |
|-----------|--------------|
| `opengrade-ai` | `import opengrade` / console script `opengrade` |
| `opengrade-ai-server` | `opengrade_server` / console script `opengrade-server` |

### One-time setup (Trusted Publishing)

1. Create a GitHub Environment named **`pypi`** on `19Alma98/ai-eval-platform` (optional protection rules / required reviewers).
2. On [PyPI](https://pypi.org/manage/account/publishing/): for **each** of `opengrade-ai` and `opengrade-ai-server`, add a **pending** trusted publisher:
   - Owner: `19Alma98`
   - Repository: `ai-eval-platform`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. No API tokens are required.

### Release steps

The git tag is the only source of the version. Both packages read it through [hatch-vcs](https://github.com/ofek/hatch-vcs); `opengrade.__version__`, `opengrade_server.__version__` and the API's OpenAPI version read the installed package metadata. Untagged builds get a dev version such as `0.1.1.dev3+g1a2b3c4`.

1. Tag the commit and push the tag: `git tag v0.1.0 && git push origin v0.1.0`
2. The workflow builds the UI (`package-ui.sh`) and both wheels with `OPENGRADE_RELEASE_BUILD=1`. That makes each package's `hatch_build.py` pin its sibling to the same version: the server needs `opengrade-ai==X`, and `opengrade-ai[ui]` needs `opengrade-ai-server==X`. Dev builds leave those requirements unpinned so `uv.lock` stays stable. Building a non-dev (tagged) version without `OPENGRADE_RELEASE_BUILD=1` fails in `hatch_build.py` so unpinned release wheels cannot be published by accident.
3. The workflow checks that both wheels carry the tag's version and the exact pins, and that `_ui/index.html` is inside the server wheel. Then it uploads via OIDC.

Dry-run (build only, no upload): Actions → **Publish** → Run workflow → leave **dry_run** checked.

Install for users after publish:

```bash
pip install 'opengrade-ai[ui]'
opengrade ui
```

## CI integration

See `.github/workflows/release-gate.yml.example` and `examples/opengrade.yaml`.

Preferred (evaluate + gate in one step):

```yaml
- name: RAG evaluate + quality gate
  env:
    LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
  run: opengrade evaluate --config opengrade.yaml --name "ci-${GITHUB_SHA::7}"
```

Standalone check against an experiment that already exists on a remote API:

```yaml
- name: Run AI evaluation gate
  run: opengrade check --policy opengrade.yaml
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
