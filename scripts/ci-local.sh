#!/usr/bin/env bash
# Run the same checks as .github/workflows/ci.yml locally.
# Usage (from repo root): ./scripts/ci-local.sh
# Optional filters: ./scripts/ci-local.sh backend sdk
#                   ./scripts/ci-local.sh frontend
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -eq 0 ]]; then
  set -- backend sdk frontend
fi

run_python_job() {
  local dir="$1"
  local mypy_pkg="$2"
  local sync_args="$3"

  echo "==> $dir"
  cd "$ROOT/$dir"
  # shellcheck disable=SC2086
  uv sync $sync_args
  uv run ruff check src
  uv run ruff format --check src
  uv run mypy "$mypy_pkg"
  uv run pytest -v
}

run_frontend() {
  echo "==> frontend"
  cd "$ROOT/frontend"
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
  npm run typecheck
}

for job in "$@"; do
  case "$job" in
    backend)
      echo "==> package-ui"
      "$ROOT/scripts/package-ui.sh"
      run_python_job backend src/aiobs_server "--all-extras"
      ;;
    sdk)      run_python_job sdk src/aiobs "--extra dev" ;;
    frontend) run_frontend ;;
    *)
      echo "Unknown job: $job (expected: backend sdk frontend)" >&2
      exit 2
      ;;
  esac
done

echo "OK: all selected CI checks passed."
