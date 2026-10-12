import assert from "node:assert/strict";
import { test } from "node:test";
import type { LiveInteractionScore } from "@/lib/api/types";
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
