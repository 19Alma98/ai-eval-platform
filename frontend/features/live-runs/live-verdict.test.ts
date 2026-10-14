import assert from "node:assert/strict";
import { test } from "node:test";
import type { LiveInteractionScore, TraceScore } from "@/lib/api/types";
import { liveVerdict } from "./live-verdict";

const score = (label: string | null): LiveInteractionScore => ({
  id: "s",
  live_interaction_id: "l",
  evaluator_id: null,
  kind: "groundedness",
  score: null,
  label,
  explanation: null,
  threshold: null,
  created_at: "2026-01-01T00:00:00Z",
});

test("liveVerdict summarizes judge scores", () => {
  assert.equal(liveVerdict({ judge_status: "pending", scores: [] }), "waiting");
  assert.equal(liveVerdict({ judge_status: "error", scores: [] }), "error");
  assert.equal(liveVerdict({ judge_status: "scored", scores: [score("PASS"), score("FAIL")] }), "failing");
  assert.equal(liveVerdict({ judge_status: "scored", scores: [score("PASS"), score("SKIPPED")] }), "passing");
  assert.equal(liveVerdict({ judge_status: "scored", scores: [score("SKIPPED")] }), "not_scored");
});

test("liveVerdict fails on a failing trace score", () => {
  const traceFail: TraceScore = {
    id: "t",
    trace_id: "ab".repeat(16),
    name: "user_feedback",
    value: 0,
    label: "FAIL",
    explanation: null,
    threshold: null,
    source: "human",
    author: "u",
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
  assert.equal(
    liveVerdict({ judge_status: "scored", scores: [score("PASS")], trace_scores: [traceFail] }),
    "failing",
  );
  assert.equal(liveVerdict({ judge_status: "pending", scores: [], trace_scores: [traceFail] }), "failing");
  assert.equal(liveVerdict({ judge_status: "scored", scores: [score("PASS")], trace_scores: [] }), "passing");
});

test("liveVerdict ignores non-FAIL trace labels and a missing trace_scores", () => {
  const traceScore = (label: string): TraceScore => ({
    id: "t",
    trace_id: "ab".repeat(16),
    name: "m",
    value: null,
    label,
    explanation: null,
    threshold: null,
    source: "sdk",
    author: null,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  assert.equal(
    liveVerdict({ judge_status: "scored", scores: [score("PASS")], trace_scores: [traceScore("ERROR")] }),
    "passing",
  );
  assert.equal(liveVerdict({ judge_status: "error", scores: [], trace_scores: [traceScore("FAIL")] }), "failing");
  assert.equal(liveVerdict({ judge_status: "error", scores: [] }), "error");
  assert.equal(liveVerdict({ judge_status: "scored", scores: [score("PASS")] }), "passing");
});
