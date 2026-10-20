import assert from "node:assert/strict";
import { test } from "node:test";
import { describeCheck, policyFromQualityBar } from "./describe-check";

test("describeCheck humanizes check ids", () => {
  assert.deepEqual(
    describeCheck({ metric: "groundedness.min", actual: 0.708, threshold: 0.7, status: "passed" }),
    {
      key: "groundedness.min",
      title: "Groundedness average score",
      actual: "0.71",
      target: "≥ 0.70",
      outcome: "passed",
      isRegression: false,
    },
  );
  const latency = describeCheck({ metric: "latency.p95", actual: 1500, threshold: 30000, status: "passed" });
  assert.equal(latency.actual, "1.50 s");
  assert.equal(latency.target, "≤ 30.00 s");
  const regression = describeCheck({
    metric: "regression.must_contain.mean_score",
    actual: -0.5,
    threshold: -0.05,
    status: "failed",
  });
  assert.equal(regression.title, "Required phrases vs baseline");
  assert.equal(regression.actual, "−50 pts");
  assert.equal(regression.outcome, "failed");
  assert.ok(regression.isRegression);
  assert.equal(
    describeCheck({ metric: "x.min", actual: null, threshold: 1, status: "unavailable" }).outcome,
    "unavailable",
  );
});

test("describeCheck renders run-metric bounds with the backend's sign", () => {
  assert.deepEqual(
    describeCheck({
      metric: "experiment_metrics.latency_p50_ms.max",
      actual: 1850,
      threshold: 2000,
      status: "passed",
    }),
    {
      key: "experiment_metrics.latency_p50_ms.max",
      title: "Run metric latency_p50_ms",
      actual: "1,850",
      target: "≤ 2,000",
      outcome: "passed",
      isRegression: false,
    },
  );
  const min = describeCheck({
    metric: "experiment_metrics.cost_usd.min",
    actual: 0.01234,
    threshold: 0.005,
    status: "passed",
  });
  assert.equal(min.target, "≥ 0.005");
  assert.equal(min.actual, "0.0123");
});

test("policyFromQualityBar builds the API policy", () => {
  assert.deepEqual(
    policyFromQualityBar({
      rules: [
        { name: "correctness", enabled: true, min: "0.7" },
        { name: "mrr", enabled: false, min: "0.5" },
        { name: "latency", enabled: true, min: "1" },
      ],
      latencyEnabled: true,
      latencySeconds: "30",
      regressionEnabled: true,
      regressionPoints: "5",
    }),
    {
      correctness: { min: 0.7 },
      latency: { p95_max_ms: 30000 },
      regression: { max_delta: -0.05 },
    },
  );
});
