# Contributing to OpenGrade

Thanks for helping. Bug reports, docs fixes, new metrics and examples are all welcome: open an
[issue](https://github.com/19Alma98/ai-eval-platform/issues) to discuss anything larger than a
small fix before you start.

## Repository layout

| Directory | Package | What it is |
|---|---|---|
| `sdk/` | `opengrade-ai` | Python SDK and the `opengrade` command |
| `backend/` | `opengrade-ai-server` | FastAPI server: OTLP ingest, REST API, metrics and LLM judges, CLI (`opengrade ui`, `evaluate`, `check`) |
| `frontend/` | (bundled into the server wheel) | Next.js UI, exported as static files |
| `docs/` | | MkDocs site, plus the design notes |
| `examples/` | | runnable demos, most of them offline |
| `scripts/` | | UI packaging, judge sanity suite, docs hooks, smoke tests |

The two Python packages are always released together with the same version.

## Set up

Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/), Node.js ≥ 22.

```bash
python scripts/package_ui.py                       # build the UI into backend/src/opengrade_server/_ui
cd backend && uv sync --all-extras && uv run opengrade ui    # http://127.0.0.1:8000
cd sdk && uv sync
cd frontend && npm ci && npm run dev               # UI dev server on :3000, proxies /api to :8000
```

## Checks

`./scripts/ci-local.sh` runs what CI runs (`./scripts/ci-local.sh backend sdk` or `frontend` for a
subset). Per package:

```bash
# backend/ and sdk/
uv run ruff check src && uv run ruff format --check src
uv run mypy src/opengrade_server        # sdk/: uv run mypy src/opengrade
uv run pytest

# frontend/
npm run typecheck && npm run lint && npm test
```

Some PostgreSQL tests are skipped unless a database is available; the CI job provides one.

### Changing judge prompts

Every LLM judge prompt is versioned by a hash of its text, so scores from different prompts are
never compared as if they were the same metric. If you change a prompt in
`backend/src/opengrade_server/evaluation/judges/prompts.py`:

1. update `backend/tests/fixtures/judge_prompts/system_templates.json` in the same commit
   (`test_system_templates_match_golden_fixture` fails until you do);
2. mention it in the changelog: it changes `prompt_version` and resets baseline comparisons for
   that judge;
3. if you can, run the judge sanity suite against a real model
   ([`scripts/judge_sanity.py`](scripts/judge_sanity.py), see
   [Metrics and judges](docs/03-evaluation-engine.md#judge-sanity-suite-meta-eval)).

## Documentation

The site is built from `docs/`, plus `sdk/README.md` (the SDK page, also shown on PyPI),
`CHANGELOG.md` and this file. Preview it from the repository root:

```bash
uv run --project sdk --only-group docs mkdocs serve      # http://127.0.0.1:8000
uv run --project sdk --only-group docs mkdocs build --strict
```

Write links as normal repository-relative Markdown links: the hook in
[`scripts/docs/links.py`](scripts/docs/links.py) turns them into site pages or GitHub URLs. The
site is deployed by [`.github/workflows/docs.yml`](.github/workflows/docs.yml) on every push to
`main`.

## Pull requests

- Keep a PR to one change, with tests for behaviour changes.
- Add a line under **[Unreleased]** in [`CHANGELOG.md`](CHANGELOG.md). Breaking changes go under
  **Changed** with a migration note (while the version is `0.x`, minor releases may break).
- CI must be green: lint, format, mypy (strict), tests and the end-to-end UI smoke test.

## Releasing

Maintainers only. Workflow: [`.github/workflows/publish.yml`](.github/workflows/publish.yml).

| Artifact | Name |
|----------|------|
| PyPI SDK | `opengrade-ai` — `import opengrade` / console script `opengrade` |
| PyPI server | `opengrade-ai-server` — `opengrade_server` / console script `opengrade-server` |
| Container | `ghcr.io/19alma98/ai-eval-platform/opengrade` — API + packaged UI (non-root `10001`) |

### One-time setup (Trusted Publishing + GHCR)

1. Create a GitHub Environment named **`pypi`** on `19Alma98/ai-eval-platform` (optional protection rules / required reviewers).
2. On [PyPI](https://pypi.org/manage/account/publishing/): for **each** of `opengrade-ai` and `opengrade-ai-server`, add a **pending** trusted publisher:
   - Owner: `19Alma98`
   - Repository: `ai-eval-platform`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. No API tokens are required for PyPI or GHCR (`GITHUB_TOKEN` with `packages: write` on the docker job).
4. After the first image push, open the package on GitHub → **Package settings** → set visibility to **Public** if anonymous `docker pull` should work.

### Release steps

The git tag is the only source of the version. Both packages read it through [hatch-vcs](https://github.com/ofek/hatch-vcs); `opengrade.__version__`, `opengrade_server.__version__` and the API's OpenAPI version read the installed package metadata. Untagged builds get a dev version such as `0.1.1.dev3+g1a2b3c4`.

1. Move the **[Unreleased]** entries of `CHANGELOG.md` under a new `## [X.Y.Z] - YYYY-MM-DD` heading and commit.
2. Tag the commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
3. The workflow builds the UI (`package-ui.sh`) and both wheels with `OPENGRADE_RELEASE_BUILD=1`. That makes each package's `hatch_build.py` pin its sibling to the same version: the server needs `opengrade-ai==X`, and `opengrade-ai[ui]` needs `opengrade-ai-server==X`. Dev builds leave those requirements unpinned so `uv.lock` stays stable. Building a non-dev (tagged) version without `OPENGRADE_RELEASE_BUILD=1` fails in `hatch_build.py` so unpinned release wheels cannot be published by accident.
4. The workflow checks that both wheels carry the tag's version and the exact pins, and that `_ui/index.html` is inside the server wheel. Then it uploads via OIDC and pushes `opengrade:<version>` plus `opengrade:latest` to GHCR (same version string, `OPENGRADE_RELEASE_BUILD=1` in the image build).
5. Check the published packages: `uvx --refresh --from 'opengrade-ai[ui]==X.Y.Z' opengrade ui`. The *Install smoke* workflow also runs [`scripts/smoke_install.py`](scripts/smoke_install.py) against PyPI after each release.
6. If an example pins the SDK (`examples/sdk_tour/pyproject.toml`), raise the pin and run `uv lock --upgrade-package opengrade-ai` there.

Dry-run (build wheels and image only; no PyPI upload, no GHCR push): Actions → **Publish** → Run workflow → leave **dry_run** checked.

## License

By contributing you agree that your contributions are licensed under the
[Apache-2.0](LICENSE) license of the project.
