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

Flags override YAML: `--task`, `--script`, `--dataset`, `--metrics`, `--name`, `--baseline`, `--from-experiment`, `--version`, `--promote`, `--require-baseline` / `--allow-missing-baseline`, `--base-url`, `--project`, `--backend-store-uri`, `--json`. Report files (flags only): `--report-md PATH`, `--junit PATH`; `--show-regressions N` (default 10, `0` = off) lists the test cases that got worse.

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

#### Require a baseline on pull requests (`--require-baseline`)

By default a run with no comparable baseline (alias not set yet, or exam changed) skips every rule that compares with the baseline and can still pass: right for the first run on `main`, wrong for a pull request, which would go green without being compared with anything (e.g. the CI cache holding the baseline expired).

`--require-baseline` (YAML `evaluate.require_baseline: true`) turns that into a failure: the absolute rules are still evaluated and reported, and a failed check `baseline.required` is added (exit `1`, no promotion). It needs `baseline` / `from_experiment` and at least one baseline rule in the policy (exit `2` otherwise). `--allow-missing-baseline` overrides a YAML `true`.

```bash
# pull_request: must be compared with main
opengrade evaluate --config opengrade.yaml --baseline alias:main --require-baseline
# push to main: may bootstrap / re-base the alias
opengrade evaluate --config opengrade.yaml --baseline alias:main --promote main
```

A PR that intentionally changes the exam (new gold items, another metrics set) cannot be compared with `main`: run it without `--require-baseline` (e.g. behind a PR label, see `examples/ci_regression_gate/github-workflow.yml.example`); merging it re-bases the alias.

With a policy that only has baseline rules, the first run without a baseline has nothing to gate on: it passes (and `--promote` bootstraps the alias) instead of failing with an empty policy.

#### Latency, cost and run metrics vs the baseline

`regression` compares evaluator scores. Latency, cost and run-level metrics have relative bounds too, next to their absolute ones:

```yaml
latency:
  p95_max_ms: 2000
  max_increase_pct: 25        # p95 at most 25% above the baseline p95
cost:
  max_per_request_usd: 0.01
  max_increase_pct: 10        # mean cost per request at most 10% above the baseline
experiment_metrics:
  opengrade.error_rate:       # logged by every evaluate run
    max: 0.05
    max_increase: 0.01        # at most +1 point of task errors vs the baseline
  accuracy:                   # higher is better: guard decreases
    max_decrease_pct: 2
```

Checks: `latency.p95.max_increase_pct`, `cost.mean_per_request_usd.max_increase_pct`, `experiment_metrics.<key>.max_increase|max_decrease|max_increase_pct|max_decrease_pct`. `actual` is the change in the guarded direction (percent for `*_pct`). Unlike `regression` these are plain comparisons, not a significance test: wall-clock latency on shared CI runners is noisy, so keep `max_increase_pct` generous or use `repeats`. Like `regression`, they are dropped on a run without a baseline (or fail it with `--require-baseline`).

#### Which test cases got worse (`--show-regressions`)

When the run has a baseline, the output lists up to `N` test cases (default 10) whose score dropped on at least one metric: the input, the baseline and candidate outputs, and per metric `baseline → candidate` score and label (`hit_at_k: 1.000 PASS → 0.000 FAIL`). Cases that regressed on more metrics come first, then the largest total drop. The same list goes into `--json` (`regressed_items`, `regressed_items_total`), the Markdown report (table plus collapsible full outputs with the evaluator's explanation) and the JUnit failure of each `regression.<metric>.mean_score` check, with a link to the side-by-side compare page (`compare_url`).

A case counts as worse when its score drops by more than the compare threshold, item by item, so the list can be non-empty while the aggregate `regression` check passes (some cases up, some down). It is diagnostic only: it never changes the gate result, and a failure to fetch it is a warning.

#### Reports: job summary, PR comment, JUnit

```bash
opengrade evaluate --config opengrade.yaml --baseline alias:main --require-baseline \
  --report-md "$GITHUB_STEP_SUMMARY" --junit opengrade-junit.xml
```

- `--report-md PATH` writes a Markdown report: verdict, candidate / baseline experiment and commits (with a code-diff link), notes (no baseline, exam changed), failing checks first, per-metric deltas vs the baseline, the test cases that got worse, and all checks in a collapsible block. Model inputs / outputs are HTML-escaped and clipped so they cannot break the layout. Point it at `$GITHUB_STEP_SUMMARY` for the job summary, or at a file posted as a sticky PR comment.
- `--junit PATH` writes JUnit XML, one test case per check; `failed` and `unavailable` checks are failures. CI test-report widgets (GitLab, Jenkins, Azure DevOps, JUnit-report actions on GitHub) show them per check.

Both are written whenever the gate runs, passing or failing, and are also available on `opengrade check`. Parent directories are created.

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

`--json` output (stdout is one JSON document; diagnostics go to stderr) adds `version`, `git` / `baseline_git` (code revisions of the run and its baseline), `baseline_ref` (as configured, e.g. `alias:main`), the `baseline_id` actually used by the gate, `code_diff_url`, `compare_url`, `comparison` (per-evaluator candidate / baseline / delta / status), `regressed_items` / `regressed_items_total`, `experiment_metrics`, `notes`, and `promoted` (`{alias, experiment_id, previous_experiment_id, exam_changed}` or `null`). Aliases and their history are also available over the API (`/projects/{id}/experiment-aliases`, see `docs/05-api.md`) and the SDK (`client.experiments.set_alias / get_alias / alias_history`, `baseline="alias:main"`).

Design: [`docs/superpowers/specs/2026-10-28-opengrade-evaluate-cli-design.md`](superpowers/specs/2026-10-28-opengrade-evaluate-cli-design.md).

### Quality gate only

```text
opengrade check --policy opengrade.yaml [--base-url URL] [--project-id ID] [--experiment-id ID] [--baseline-experiment-id ID] [--report-md PATH] [--junit PATH]
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

Runnable "PR must not be worse than `main`" example (deterministic, no LLM): [`examples/ci_regression_gate/`](../examples/ci_regression_gate/README.md) — local demo script plus a GitHub Actions workflow that keeps the baseline on a shared server or in the Actions cache.

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

## GitHub integration

`--report-md` covers the job summary and PR comments (post the file with a sticky-comment action); `--junit` covers check annotations through a JUnit-report action. A native GitHub Check Run (without a third-party action) is not built in yet. Full workflow: [`examples/ci_regression_gate/github-workflow.yml.example`](../examples/ci_regression_gate/github-workflow.yml.example).

## Benchmarking

CLI should optionally emit:
- samples/sec
- evaluator duration
- total tokens
- estimated cost
- failure count
