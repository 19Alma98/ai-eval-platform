import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { MetricComparison } from "@/lib/api/types";
import { groupMetricsByEvaluator } from "./group-metrics-by-evaluator";

function metric(
  partial: Partial<MetricComparison> &
    Pick<MetricComparison, "evaluator_id" | "metric" | "status">,
): MetricComparison {
  return {
    evaluator_name: partial.evaluator_name ?? "ev",
    candidate: partial.candidate ?? null,
    baseline: partial.baseline ?? null,
    delta: partial.delta ?? null,
    ...partial,
  };
}

describe("groupMetricsByEvaluator", () => {
  it("merges mean_score and pass_rate into one row per evaluator", () => {
    const rows = groupMetricsByEvaluator([
      metric({
        evaluator_id: "a",
        evaluator_name: "must_contain",
        metric: "mean_score",
        candidate: 0.75,
        baseline: 1,
        delta: -0.25,
        status: "regression",
      }),
      metric({
        evaluator_id: "a",
        evaluator_name: "must_contain",
        metric: "pass_rate",
        candidate: 0.5,
        baseline: 1,
        delta: -0.5,
        status: "regression",
      }),
    ]);

    assert.equal(rows.length, 1);
    assert.equal(rows[0].evaluator_name, "must_contain");
    assert.equal(rows[0].candidate_mean, 0.75);
    assert.equal(rows[0].candidate_pass_rate, 0.5);
    assert.equal(rows[0].baseline_mean, 1);
    assert.equal(rows[0].baseline_pass_rate, 1);
    assert.equal(rows[0].delta, -0.25);
    assert.equal(rows[0].status, "regression");
  });

  it("uses mean_score for delta and status, not pass_rate", () => {
    const rows = groupMetricsByEvaluator([
      metric({
        evaluator_id: "a",
        metric: "mean_score",
        delta: 0.1,
        status: "improved",
      }),
      metric({
        evaluator_id: "a",
        metric: "pass_rate",
        delta: -0.9,
        status: "regression",
      }),
    ]);

    assert.equal(rows[0].delta, 0.1);
    assert.equal(rows[0].status, "improved");
  });

  it("sorts regressions before improvements", () => {
    const rows = groupMetricsByEvaluator([
      metric({
        evaluator_id: "good",
        metric: "mean_score",
        status: "improved",
      }),
      metric({
        evaluator_id: "bad",
        metric: "mean_score",
        status: "regression",
      }),
    ]);

    assert.equal(rows[0].evaluator_id, "bad");
    assert.equal(rows[1].evaluator_id, "good");
  });

  it("marks status unavailable when mean_score is missing", () => {
    const rows = groupMetricsByEvaluator([
      metric({
        evaluator_id: "a",
        metric: "pass_rate",
        candidate: 0.5,
        baseline: 1,
        delta: -0.5,
        status: "regression",
      }),
    ]);

    assert.equal(rows[0].status, "unavailable");
    assert.equal(rows[0].delta, null);
    assert.equal(rows[0].candidate_pass_rate, 0.5);
  });
});
