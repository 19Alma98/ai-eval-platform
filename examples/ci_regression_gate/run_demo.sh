#!/usr/bin/env bash
# Local walkthrough of the CI regression gate: no LLM, no server, ~30 s.
#
#   1. "push to main"   → first run, no baseline yet → gate passes → alias main promoted
#   2. "PR, no change"  → equal to baseline          → PASS (exit 0)
#   3. "PR, regressed"  → buggy tokenizer refactor   → FAIL (exit 1), alias not moved
#
# The baseline alias lives in ./ci.db (a durable SQLite file standing in for your
# shared OpenGrade server / persisted CI database).
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

OPENGRADE=${OPENGRADE:-"uv run -q --project ../../backend opengrade"}
STORE="sqlite+aiosqlite:///$PWD/ci.db"
rm -f ci.db ci.db-wal ci.db-shm

run() {  # run <label> <expected-exit> [extra args…]
  local label=$1 expected=$2; shift 2
  echo; echo "=== $label ==="
  $OPENGRADE evaluate --config opengrade.yaml --backend-store-uri "$STORE" "$@" 2>&1 \
    | grep -v '^INFO  \[alembic'
  local code=${PIPESTATUS[0]}
  echo "--> exit code $code (expected $expected)"
  [[ $code == "$expected" ]] || { echo "unexpected exit code"; exit 1; }
}

run "1. push to main: bootstrap baseline" 0 --version main-1 --promote main
run "2. PR: refactor with same quality"   0 --version pr-1
RAG_TOKENIZER=raw \
run "3. PR: buggy tokenizer refactor"     1 --version pr-2 --promote main

echo; echo "Demo OK: equal-or-better passes, worse is blocked."
