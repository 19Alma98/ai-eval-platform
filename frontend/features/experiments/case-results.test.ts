import assert from "node:assert/strict";
import { test } from "node:test";
import type { DatasetItem, EvaluationRun, EvaluatorSummary } from "@/lib/api/types";
import {
  buildCaseViews,
  contextStats,
  outcomeOf,
  parseRetrievedDocuments,
} from "./case-results";

const item = (id: string): DatasetItem => ({
  id,
  dataset_id: "d",
  input: `q-${id}`,
  expected_output: "a",
  actual_output: null,
  context: null,
  metadata: { expected_doc_ids: ["pto"] },
  source_trace_id: null,
  source_span_id: null,
});

const summary = (name: string, runId: string): EvaluatorSummary => ({
  evaluator_id: `ev-${name}`,
  evaluator_name: name,
  run_id: runId,
  status: "completed",
  n_items: 2,
  n_scored: 2,
  n_error: 0,
  n_skipped: 0,
  mean_score: 0.5,
  pass_rate: 0.5,
});

const run = (id: string, rows: [string, string, number][]): EvaluationRun => ({
  id,
  experiment_id: "e",
  evaluator_id: "x",
  status: "completed",
  started_at: null,
  finished_at: null,
  metadata: {},
  results: rows.map(([itemId, label, score]) => ({
    id: `${id}-${itemId}`,
    run_id: id,
    dataset_item_id: itemId,
    score,
    label,
    explanation: null,
    metadata: {},
    duration_ms: null,
  })),
});

test("outcomeOf maps labels", () => {
  assert.equal(outcomeOf("PASS", 1), "pass");
  assert.equal(outcomeOf("FAIL", 0), "fail");
  assert.equal(outcomeOf("SKIPPED", null), "skipped");
  assert.equal(outcomeOf(null, 0.4), "scored");
  assert.equal(outcomeOf(null, null), "pending");
});

test("buildCaseViews attaches every metric and lists failures", () => {
  const runs = new Map([
    ["r1", run("r1", [["i1", "PASS", 1], ["i2", "FAIL", 0]])],
    ["r2", run("r2", [["i1", "FAIL", 0.2]])],
  ]);
  const cases = buildCaseViews(
    [item("i1"), item("i2")],
    [],
    [summary("latency", "r1"), summary("groundedness", "r2")],
    runs,
  );
  assert.equal(cases.length, 2);
  // answer quality metrics sort before performance
  assert.equal(cases[0]!.results[0]!.metric.label, "Groundedness");
  assert.equal(cases[0]!.nPassed, 1);
  assert.equal(cases[0]!.nScored, 2);
  assert.deepEqual(cases[0]!.failed.map((r) => r.metric.name), ["groundedness"]);
  // missing result in a loaded run means the metric skipped this case
  assert.equal(cases[1]!.results[0]!.outcome, "skipped");
});

test("parseRetrievedDocuments normalizes shapes", () => {
  assert.equal(parseRetrievedDocuments(undefined), null);
  assert.deepEqual(parseRetrievedDocuments([{ id: "pto", title: "PTO", text: "20 days" }, "raw"]), [
    { id: "pto", title: "PTO", text: "20 days" },
    { id: null, title: null, text: "raw" },
  ]);
});

test("contextStats formats latency and tokens", () => {
  assert.deepEqual(contextStats({ latency_ms: 532.09, total_tokens: 1200 }), [
    { label: "Response time", value: "532 ms" },
    { label: "Tokens", value: (1200).toLocaleString() },
  ]);
  assert.deepEqual(contextStats("nope"), []);
});
