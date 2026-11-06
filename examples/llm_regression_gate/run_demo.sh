#!/usr/bin/env bash
# Local walkthrough of the LLM regression gate (needs Ollama, ~5-15 min on a laptop).
#
#   ollama pull gemma4:e2b        # app model and judge (override with RAG_LLM_MODEL /
#                                 # evaluate.judge.model in opengrade.yaml)
#
#   1. "push to main"            → bootstrap, gate passes → alias main promoted
#   2. "PR, no code change"      → same code, new LLM samples → PASS: noise is not a regression
#   3. "PR, context dropped"     → generation answers from memory → FAIL (exit 1):
#                                  critical questions fail, groundedness drops
#
# Step 2 is the point of this example: with a sampling LLM two runs of the same code never give the same answers. repeats + the paired bootstrap keep that from failing CI. If step 2 fails on your machine, look at which check failed: a judge floor (min) too close to the model's real score, or a gold set too small (min_detectable_delta).
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

opengrade_cli() {
  if [[ -n "${OPENGRADE:-}" ]]; then
    $OPENGRADE "$@"
  else
    uvx --from 'opengrade-ai[ui,openai]' opengrade "$@"
  fi
}
STORE="sqlite+aiosqlite:///$PWD/ci.db"
rm -rf ci.db ci.db-wal ci.db-shm

run() {  # run <step> <label> <expected-exit> [extra args…]
  local step=$1 label=$2 expected=$3; shift 3
  echo; echo "=== $step. $label ==="
  opengrade_cli evaluate --config opengrade.yaml --backend-store-uri "$STORE" \
    "$@" 2>&1 | grep -v '^INFO  \[alembic'
  local code=${PIPESTATUS[0]}
  echo "--> exit code $code (expected $expected)"
  [[ $code == "$expected" ]] || { echo "unexpected exit code"; exit 1; }
}

run 1 "push to main: bootstrap baseline"          0 --version main-1 --promote main
run 2 "PR: no code change, new LLM samples"       0 --version pr-1 --require-baseline
RAG_PROMPT=no_context \
run 3 "PR: refactor drops the retrieved context"  1 --version pr-2 --require-baseline

echo; echo "Demo OK: LLM noise passes, a real generation regression is blocked."
