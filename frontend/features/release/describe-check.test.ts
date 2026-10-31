import assert from "node:assert/strict";
import { test } from "node:test";
import { describeCheck, policyFromQualityBar } from "./describe-check";

const emptyExtras = {
  costEnabled: false,
  costMaxUsd: "0.05",
  experimentMetricRules: [] as { key: string; enabled: boolean; bound: string }[],
  groupsEnabled: false,
  groupsBy: "",
  groupsMinItems: "5",
  groupsMaxDeltaPoints: "",
};

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
  assert.match(regression.target, /95% CI/);
  assert.match(regression.target, /mean floor/);
  const bootstrapOnly = describeCheck({
    metric: "regression.groundedness.mean_score",
    actual: -0.1,
    threshold: null,
    status: "failed",
  });
  assert.equal(bootstrapOnly.target, "no significant drop (95% CI)");
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

test("describeCheck humanizes per-group checks", () => {
  const min = describeCheck({
    metric: "groups.category=billing.groundedness.min",
    actual: 0.62,
    threshold: 0.7,
    status: "failed",
  });
  assert.equal(min.title, "Groundedness in category=billing");
  assert.equal(min.actual, "0.62");
  assert.equal(min.target, "≥ 0.70");
  assert.equal(min.isRegression, false);

  const reg = describeCheck({
    metric: "groups.category=billing.regression.groundedness.mean_score",
    actual: -0.12,
    threshold: -0.05,
    status: "failed",
  });
  assert.equal(reg.title, "Groundedness in category=billing vs baseline");
  assert.equal(reg.actual, "−12 pts");
  assert.ok(reg.isRegression);
  assert.match(reg.target, /mean floor/);
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
      ...emptyExtras,
    }),
    {
      correctness: { min: 0.7 },
      latency: { p95_max_ms: 30000 },
      regression: { max_delta: -0.05 },
    },
  );
  assert.deepEqual(
    policyFromQualityBar({
      rules: [],
      latencyEnabled: false,
      latencySeconds: "30",
      regressionEnabled: true,
      regressionPoints: "",
      ...emptyExtras,
    }),
    { regression: {} },
  );
});

test("policyFromQualityBar emits cost, experiment_metrics, and groups", () => {
  assert.deepEqual(
    policyFromQualityBar({
      rules: [{ name: "groundedness", enabled: true, min: "0.7" }],
      latencyEnabled: false,
      latencySeconds: "30",
      regressionEnabled: true,
      regressionPoints: "5",
      costEnabled: true,
      costMaxUsd: "0.02",
      experimentMetricRules: [
        { key: "cost_usd", enabled: true, bound: "1.5" },
        { key: "accuracy", enabled: true, bound: "0.9" },
        { key: "ignored", enabled: false, bound: "1" },
      ],
      groupsEnabled: true,
      groupsBy: "category",
      groupsMinItems: "5",
      groupsMaxDeltaPoints: "10",
    }),
    {
      groundedness: { min: 0.7 },
      regression: { max_delta: -0.05 },
      cost: { max_per_request_usd: 0.02 },
      experiment_metrics: {
        cost_usd: { max: 1.5 },
        accuracy: { min: 0.9 },
      },
      groups: { by: "category", min_items: 5, max_delta: -0.1 },
    },
  );
  assert.deepEqual(
    policyFromQualityBar({
      rules: [{ name: "groundedness", enabled: true, min: "0.7" }],
      latencyEnabled: false,
      latencySeconds: "30",
      regressionEnabled: false,
      regressionPoints: "",
      costEnabled: false,
      costMaxUsd: "0.05",
      experimentMetricRules: [],
      groupsEnabled: true,
      groupsBy: "lang",
      groupsMinItems: "3",
      groupsMaxDeltaPoints: "",
    }),
    {
      groundedness: { min: 0.7 },
      groups: { by: "lang", min_items: 3 },
    },
  );
});

test("describeCheck covers relative bounds vs baseline", () => {
  const latency = describeCheck({
    metric: "latency.p95.max_increase_pct",
    actual: 31.25,
    threshold: 20,
    status: "failed",
  });
  assert.equal(latency.title, "Latency (95% of answers) vs baseline");
  assert.equal(latency.actual, "+31.3%");
  assert.equal(latency.target, "increase ≤ 20%");
  assert.ok(latency.isRegression);

  const cost = describeCheck({
    metric: "cost.mean_per_request_usd.max_increase_pct",
    actual: null,
    threshold: 10,
    status: "unavailable",
  });
  assert.equal(cost.title, "Average cost per answer vs baseline");
  assert.equal(cost.actual, "—");
  assert.equal(cost.outcome, "unavailable");

  const errors = describeCheck({
    metric: "experiment_metrics.opengrade.error_rate.max_increase",
    actual: 0.05,
    threshold: 0.01,
    status: "failed",
  });
  assert.equal(errors.title, "Run metric opengrade.error_rate vs baseline");
  assert.equal(errors.actual, "0.05");
  assert.equal(errors.target, "increase ≤ 0.01");

  const accuracy = describeCheck({
    metric: "experiment_metrics.accuracy.max_decrease_pct",
    actual: -2,
    threshold: 5,
    status: "passed",
  });
  assert.equal(accuracy.actual, "−2.0%");
  assert.equal(accuracy.target, "decrease ≤ 5%");

  const plainMax = describeCheck({
    metric: "experiment_metrics.cost_usd.max",
    actual: 1,
    threshold: 2,
    status: "passed",
  });
  assert.equal(plainMax.title, "Run metric cost_usd");
});
