#!/usr/bin/env bash
# Local walkthrough of the CI regression gate: no LLM, no server, ~30 s.
#
#   0. "PR" before main ever ran → no baseline → FAIL (--require-baseline)
#   1. "push to main"            → bootstrap, gate passes → alias main promoted
#   2. "PR, no change"           → equal to baseline      → PASS (exit 0)
#   3. "PR, regressed"           → buggy tokenizer        → FAIL (exit 1), alias not moved
#
# The baseline alias lives in ./ci.db (a durable SQLite file standing in for your
# shared OpenGrade server / persisted CI database). Markdown + JUnit reports of every
# step land in ./reports/.
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

OPENGRADE=${OPENGRADE:-"uv run -q --project ../../backend opengrade"}
STORE="sqlite+aiosqlite:///$PWD/ci.db"
rm -rf ci.db ci.db-wal ci.db-shm reports

run() {  # run <step> <label> <expected-exit> [extra args…]
  local step=$1 label=$2 expected=$3; shift 3
  echo; echo "=== $step. $label ==="
  $OPENGRADE evaluate --config opengrade.yaml --backend-store-uri "$STORE" \
    --report-md "reports/step$step.md" --junit "reports/step$step.xml" "$@" 2>&1 \
    | grep -v '^INFO  \[alembic'
  local code=${PIPESTATUS[0]}
  echo "--> exit code $code (expected $expected)"
  [[ $code == "$expected" ]] || { echo "unexpected exit code"; exit 1; }
}

run 0 "PR before any main run (--require-baseline)" 1 --version pr-0 --require-baseline
run 1 "push to main: bootstrap baseline"            0 --version main-1 --promote main
run 2 "PR: refactor with same quality"              0 --version pr-1 --require-baseline
RAG_TOKENIZER=raw \
run 3 "PR: buggy tokenizer refactor"                1 --version pr-2 --require-baseline

echo; echo "Demo OK: no baseline is blocked, equal-or-better passes, worse is blocked."
echo "Reports: $PWD/reports/step{0..3}.md (job summary / PR comment) and .xml (JUnit)"
