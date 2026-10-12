import assert from "node:assert/strict";
import { test } from "node:test";
import {
  compareMetrics,
  groupByMetricCategory,
  humanizeIdentifier,
  metricInfo,
  metricLabel,
} from "./metrics-catalog";

test("known kinds get friendly labels", () => {
  assert.equal(metricLabel("answer_relevance"), "Answer relevance");
  assert.equal(metricLabel("hit_at_k"), "Hit rate");
  assert.equal(metricInfo("groundedness").category, "generation");
});

test("unknown names are humanized, never raw snake_case", () => {
  assert.equal(metricLabel("my_custom_check"), "My custom check");
  assert.equal(metricInfo("my_custom_check").category, "other");
  assert.equal(metricLabel(null), "Unnamed metric");
  assert.equal(humanizeIdentifier("tone--check"), "Tone check");
});

test("grouping orders answer quality before retrieval and performance", () => {
  const groups = groupByMetricCategory(
    ["latency", "mrr", "correctness", "groundedness"],
    (n) => n,
  );
  assert.deepEqual(
    groups.map((g) => g.category),
    ["generation", "retrieval", "performance"],
  );
  assert.deepEqual(groups[0]!.rows, ["correctness", "groundedness"]);
  assert.ok(compareMetrics("correctness", "latency") < 0);
});
