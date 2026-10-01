#!/usr/bin/env bash
# Phase 3 smoke end-to-end: baseline vs candidate + summary/compare.
# Uses exact_match (no Ollama required).
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"

echo "health:"
curl -sf "$BASE/health" | python3 -m json.tool

echo "create project..."
PROJECT=$(curl -sf -X POST "$BASE/api/v1/projects" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"Phase3 Smoke\",\"slug\":\"phase3-smoke-$(date +%s)\"}")
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

echo "create exact_match evaluator..."
EVAL=$(curl -sf -X POST "$BASE/api/v1/projects/$PROJECT_ID/evaluators" \
  -H 'content-type: application/json' \
  -d '{"name":"exact","type":"deterministic","config":{"kind":"exact_match"}}')
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

echo "summary baseline:"
curl -sf "$BASE/api/v1/experiments/$BASELINE_ID/summary" | python3 -m json.tool

echo "compare candidate vs baseline:"
curl -sf "$BASE/api/v1/experiments/$CANDIDATE_ID/compare/$BASELINE_ID" | python3 -m json.tool

echo
echo "PROJECT_ID=$PROJECT_ID"
echo "BASELINE_ID=$BASELINE_ID"
echo "CANDIDATE_ID=$CANDIDATE_ID"
echo "EVAL_ID=$EVAL_ID"
