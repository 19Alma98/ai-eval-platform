import assert from "node:assert/strict";
import { test } from "node:test";
import type { TraceScore } from "@/lib/api/types";
import { FEEDBACK_NAME, feedbackThumb } from "./trace-feedback";

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

const fb = (over: Partial<TraceScore>) => ts({ name: FEEDBACK_NAME, ...over });

test("feedbackThumb is null without feedback rows", () => {
  assert.equal(feedbackThumb(undefined), null);
  assert.equal(feedbackThumb([]), null);
  assert.equal(feedbackThumb([ts({ name: "quality" })]), null);
});

test("feedbackThumb derives from label, falling back to value", () => {
  assert.equal(feedbackThumb([fb({ label: "PASS", value: 1 })]), "up");
  assert.equal(feedbackThumb([fb({ label: "FAIL", value: 0 })]), "down");
  assert.equal(feedbackThumb([fb({ label: "FAIL", value: 1 })]), "down");
  assert.equal(feedbackThumb([fb({ label: null, value: 0 })]), "down");
  assert.equal(feedbackThumb([fb({ label: null, value: 1 })]), "up");
});

test("feedbackThumb skips rows with neither label nor value", () => {
  assert.equal(feedbackThumb([fb({ label: null, value: null })]), null);
  assert.equal(
    feedbackThumb([fb({ label: null, value: null }), fb({ label: "PASS", value: 1 })]),
    "up",
  );
});

test("feedbackThumb ignores non-feedback FAIL rows", () => {
  assert.equal(
    feedbackThumb([ts({ name: "quality", label: "FAIL", value: 0 }), fb({ label: "PASS" })]),
    "up",
  );
  assert.equal(feedbackThumb([ts({ name: "quality", label: "FAIL", value: 0 })]), null);
});

test("feedbackThumb is down if any user gave a thumbs-down", () => {
  assert.equal(
    feedbackThumb([
      fb({ author: "a", label: "FAIL", value: 0, updated_at: "2026-10-14T10:00:00Z" }),
      fb({ author: "b", label: "PASS", value: 1, updated_at: "2026-10-14T11:00:00Z" }),
    ]),
    "down",
  );
});
