#!/usr/bin/env bash
# Local walkthrough of the non-inferiority gate: no LLM, no server, ~30 s.
#
#   1. "push to main"                     → bootstrap baseline, alias main promoted
#   2. "PR, refactor, same answers"       → CI [0, 0]                  → PASS
#   3. "PR, loses a document" (classic)   → 2/20 answers break, Δ -0.10, not significant
#                                           → PASS: the default check lets it ship
#   4. same PR, non-inferiority           → CI lower bound ≈ -0.25 < -0.05 → FAIL
#
# Reuses the toy pipeline and the gold set of examples/ci_regression_gate. The baseline
# alias lives in ./ci.db; Markdown + JUnit reports of every step land in ./reports/.
set -uo pipefail
cd "$(dirname "$0")"

OPENGRADE=${OPENGRADE:-"uv run -q --project ../../backend opengrade"}
STORE="sqlite+aiosqlite:///$PWD/ci.db"
rm -rf ci.db ci.db-wal ci.db-shm reports

run() {  # run <step> <label> <config> <expected-exit> [extra args…]
  local step=$1 label=$2 config=$3 expected=$4; shift 4
  echo; echo "=== $step. $label ==="
  $OPENGRADE evaluate --config "$config" --backend-store-uri "$STORE" \
    --report-md "reports/step$step.md" --junit "reports/step$step.xml" "$@" 2>&1 \
    | grep -v '^INFO  \[alembic'
  local code=${PIPESTATUS[0]}
  echo "--> exit code $code (expected $expected)"
  [[ $code == "$expected" ]] || { echo "unexpected exit code (see reports/step$step.md)"; exit 1; }
}

run 1 "push to main: bootstrap baseline"           opengrade.yaml         0 --version main-1 --promote main
run 2 "PR: refactor, same answers"                 opengrade.yaml         0 --version pr-1 --require-baseline
RAG_DROP_DOC=travel \
run 3 "PR loses a document, classic policy"        opengrade.classic.yaml 0 --version pr-2 --require-baseline
RAG_DROP_DOC=travel \
run 4 "same PR, non-inferiority policy"            opengrade.yaml         1 --version pr-2 --require-baseline

echo; echo "Demo OK: equal passes; a drop the test set cannot rule out is blocked only by"
echo "non_inferiority_margin. Reports: $PWD/reports/step{1..4}.md and .xml (JUnit)"
