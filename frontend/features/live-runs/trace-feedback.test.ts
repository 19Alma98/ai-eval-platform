import assert from "node:assert/strict";
import { test } from "node:test";
import type { TraceScore } from "@/lib/api/types";
import { FEEDBACK_NAME, latestFeedback } from "./trace-feedback";

const ts = (over: Partial<TraceScore>): TraceScore => ({
  id: "t",
  trace_id: "ab".repeat(16),
  name: "quality",
  value: 1,
  label: "PASS",
  explanation: null,
  threshold: null,
  source: "sdk",
  author: null,
  metadata: {},
  created_at: "2026-10-14T10:00:00Z",
  updated_at: "2026-10-14T10:00:00Z",
  ...over,
});

test("latestFeedback picks the most recent user_feedback", () => {
  assert.equal(latestFeedback([]), null);
  assert.equal(latestFeedback([ts({ name: "quality" })]), null);
  assert.equal(
    latestFeedback([
      ts({ name: FEEDBACK_NAME, value: 1, updated_at: "2026-10-14T10:00:00Z" }),
      ts({ name: FEEDBACK_NAME, value: 0, updated_at: "2026-10-14T11:00:00Z" }),
    ]),
    "down",
  );
  assert.equal(latestFeedback([ts({ name: FEEDBACK_NAME, value: 1 })]), "up");
});
