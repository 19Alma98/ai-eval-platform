#!/usr/bin/env bash
# Phase 4 smoke: evaluate candidate vs baseline, then POST release-check (+ optional CLI).
# Uses exact_match evaluators named quality (no Ollama required).
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "health:"
curl -sf "$BASE/health" | python3 -m json.tool

echo "create project..."
PROJECT=$(curl -sf -X POST "$BASE/api/v1/projects" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"Phase4 Smoke\",\"slug\":\"phase4-smoke-$(date +%s)\"}")
echo "$PROJECT" | python3 -m json.tool
PROJECT_ID=$(echo "$PROJECT" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "create good dataset..."
GOOD=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/datasets" \
  -H 'content-type: application/json' \
  -d '{"name":"support-good"}')
GOOD_ID=$(echo "$GOOD" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
curl -sf -X POST "$BASE/api/v1/datasets/$GOOD_ID/items" \
  -H 'content-type: application/json' \
  -d '{"input":"What is 2+2?","expected_output":"4","actual_output":"4"}' \
  | python3 -m json.tool

echo "create bad dataset..."
BAD=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/datasets" \
  -H 'content-type: application/json' \
  -d '{"name":"support-bad"}')
BAD_ID=$(echo "$BAD" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
curl -sf -X POST "$BASE/api/v1/datasets/$BAD_ID/items" \
  -H 'content-type: application/json' \
  -d '{"input":"What is 2+2?","expected_output":"4","actual_output":"5"}' \
  | python3 -m json.tool

echo "create quality evaluator..."
EVAL=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/evaluators" \
  -H 'content-type: application/json' \
  -d '{"name":"quality","type":"deterministic","config":{"kind":"exact_match"}}')
EVAL_ID=$(echo "$EVAL" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "create baseline experiment..."
BASELINE=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/experiments" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"baseline\",\"dataset_id\":\"$GOOD_ID\"}")
BASELINE_ID=$(echo "$BASELINE" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "create candidate experiment..."
CAND=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/experiments" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"candidate\",\"dataset_id\":\"$BAD_ID\",\"baseline_experiment_id\":\"$BASELINE_ID\"}")
CANDIDATE_ID=$(echo "$CAND" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "evaluate baseline + candidate..."
for EXP_ID in "$BASELINE_ID" "$CANDIDATE_ID"; do
  curl -sf -X POST "$BASE/api/v1/experiments/$EXP_ID/evaluate" \
    -H 'content-type: application/json' \
    -d "{\"evaluator_ids\":[\"$EVAL_ID\"]}" \
    | python3 -m json.tool
done

echo "release-check (expect failed)..."
CHECK=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/release-check" \
  -H 'content-type: application/json' \
  -d "{\"experiment_id\":\"$CANDIDATE_ID\",\"policy\":{\"quality\":{\"min\":0.85},\"regression\":{\"max_delta\":-0.03}}}")
echo "$CHECK" | python3 -m json.tool
STATUS=$(echo "$CHECK" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
if [ "$STATUS" != "failed" ]; then
  echo "expected failed release-check, got $STATUS" >&2
  exit 1
fi

POLICY_FILE=$(mktemp)
trap 'rm -f "$POLICY_FILE"' EXIT
cat > "$POLICY_FILE" <<EOF
api_base_url: $BASE
project_id: $PROJECT_ID
experiment_id: $CANDIDATE_ID
baseline_experiment_id: $BASELINE_ID
quality:
  min: 0.85
regression:
  max_delta: -0.03
EOF

echo "aiobs check (expect exit 1)..."
set +e
(
  cd "$ROOT/backend"
  uv sync --quiet
  uv run aiobs check --policy "$POLICY_FILE"
)
CLI_EXIT=$?
set -e
if [ "$CLI_EXIT" -ne 1 ]; then
  echo "expected aiobs check exit 1, got $CLI_EXIT" >&2
  exit 1
fi

echo
echo "PROJECT_ID=$PROJECT_ID"
echo "BASELINE_ID=$BASELINE_ID"
echo "CANDIDATE_ID=$CANDIDATE_ID"
echo "EVAL_ID=$EVAL_ID"
echo "phase4 release-check smoke OK"
