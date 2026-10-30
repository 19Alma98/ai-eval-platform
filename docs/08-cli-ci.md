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

Flags override YAML: `--task`, `--script`, `--dataset`, `--metrics`, `--name`, `--baseline`, `--from-experiment`, `--version`, `--promote`, `--base-url`, `--project`, `--backend-store-uri`, `--json`.

`--version` / `evaluate.version` is stored on the experiment (`experiments.version`, max 200 chars). Every run also records the git revision it measured (`experiments.git`: commit, branch, uncommitted changes, remote) from the checkout in the working directory, or from CI env vars (`GITHUB_SHA`, `CI_COMMIT_SHA`, …) when there is no `.git`; without `--version` the short SHA becomes the version. The output prints the candidate and baseline commits and, for GitHub / GitLab remotes, a link to the code diff between them; it warns when both ran the same commit. Set `OPENGRADE_DISABLE_GIT=1` to skip detection.

On GitHub `pull_request` events `actions/checkout` checks out a temporary merge commit; check out `${{ github.event.pull_request.head.sha }}` if runs should point at the PR's own commit.

#### Moving baseline (`alias:` + `--promote`)

An **experiment alias** is a named pointer (`main`, `production`, …) to the experiment that is the current baseline. `baseline` and `from_experiment` accept `alias:<name>`:

- `baseline: alias:main` — compare (and gate `regression`) against the experiment the alias points to.
- `from_experiment: alias:main` — reuse that experiment's dataset + metrics set; the baseline defaults to it.
- `promote: main` (or `--promote main`) — when the gate **passes**, move the alias to this run. A failed gate leaves it where it was. Requires policy blocks.

Without promotion the baseline never moves (`from_experiment: <uuid>`), or follows the latest run by name even when it failed the gate (`baseline: <name>`). Promotion makes it the last run that passed.

Edge cases:

- **No alias yet** (first run): the run is evaluated without a baseline, `regression` is dropped from the policy for that run, and `--promote` creates the alias. `from_experiment: alias:<name>` cannot bootstrap: it has no exam to clone (exit 2).
- **Exam changed** (another dataset or metrics set than the alias target, e.g. a new gold set): deltas would compare different exams, so `regression` is skipped for that run; when the gate passes, the alias moves (recorded as `exam changed` in its history).
- **Ratchet:** the gate fails on bootstrap `regression` (same as the compare page). Optional `max_delta` only blocks large mean drops when the CI still includes 0; repeated promotions of noisy “unchanged” runs can still drift the mean. Keep absolute `min` rules next to `regression`.

#### Gate per group (`groups`)

A global mean can pass while one kind of question collapses. `groups` re-applies the metric `min` rules and the same bootstrap regression check (plus optional mean floor) inside each group of test cases, grouped by a dataset-item metadata field:

```yaml
groundedness: {min: 0.7}
regression: {max_delta: -0.05}   # optional mean floor; bootstrap status is always gated
groups:
  by: category          # metadata key; dotted paths (meta.lang) and list values (tags) work
  min_items: 5          # smaller groups are not gated (default 5)
  # metrics: [groundedness]   # optional: only these metrics per group
  # max_delta: -0.10          # optional: looser/tighter mean floor for groups
```

Checks appear as `groups.category=billing.groundedness.min` and `groups.category=billing.regression.groundedness.mean_score`. A metric with no applicable item in a group (e.g. all SKIPPED) is not checked there. At most 50 distinct values per key. The same grouping is available without gating: `GET /experiments/{id}/summary?group_by=category`, `GET /experiments/{id}/compare/{baseline}?group_by=category`, `opengrade.evaluate(..., group_by="category")` and the "By group" section of the compare page.

Promote only from the branch that ships (push to `main`), never from pull requests: a PR that passes is not merged code. Typical workflow:

```bash
# pull_request: compare against the last accepted main run
opengrade evaluate --config opengrade.yaml --version "$GITHUB_SHA" --baseline alias:main
# push to main: same, then promote when the gate passes
opengrade evaluate --config opengrade.yaml --version "$GITHUB_SHA" --baseline alias:main --promote main
```

The alias lives in the server's database: use a persistent server (`api_base_url`) or `--backend-store-uri` pointing at a durable DB. The default embedded temp SQLite is discarded after each run.

`--json` output adds `version`, `git` / `baseline_git` (code revisions of the run and its baseline), the `baseline_id` actually used by the gate, and `promoted` (`{alias, experiment_id, previous_experiment_id, exam_changed}` or `null`). Aliases and their history are also available over the API (`/projects/{id}/experiment-aliases`, see `docs/05-api.md`) and the SDK (`client.experiments.set_alias / get_alias / alias_history`, `baseline="alias:main"`).

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
