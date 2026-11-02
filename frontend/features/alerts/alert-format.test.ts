import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  conditionDefaults,
  describeReading,
  describeRule,
  formatAlertValue,
  formatRuleValue,
  signedThreshold,
  thresholdFromInput,
  thresholdToInput,
} from "./alert-format";

describe("alert thresholds", () => {
  it("types percents as 0-100 and stores 0-1", () => {
    assert.equal(thresholdToInput("error_rate", 0.05), "5");
    assert.equal(thresholdFromInput("error_rate", "12.5"), 0.125);
    assert.equal(thresholdFromInput("latency_p90_ms", "1500"), 1500);
    assert.equal(thresholdFromInput("traffic", ""), null);
  });

  it("formats values per unit", () => {
    assert.equal(formatAlertValue("score_fail_rate", 0.354), "35.4%");
    assert.equal(formatAlertValue("latency_p99_ms", 1234.4), "1,234 ms");
    assert.equal(formatAlertValue("cost_usd", 0.12345), "$0.1235");
    assert.equal(formatAlertValue("traffic", null), "no data");
  });

  it("describes a rule", () => {
    assert.equal(
      describeRule({
        metric: "score_fail_rate",
        operator: "gt",
        threshold: 0.2,
        window_minutes: 60,
        score_name: "groundedness",
        score_source: "judge",
      }),
      "groundedness (judge) fail rate > 20.0% over 1 hour",
    );
    assert.equal(
      describeRule({
        metric: "traffic",
        operator: "lt",
        threshold: 1,
        window_minutes: 15,
        score_name: null,
        score_source: null,
      }),
      "traces (traffic) < 1 over 15 minutes",
    );
    assert.equal(
      describeRule({
        metric: "error_rate",
        operator: "gt",
        threshold: 0.05,
        window_minutes: 60,
        score_name: null,
        score_source: null,
        environment: "prod",
        version: "v2",
      }),
      "error rate > 5.0% over 1 hour (env prod, version v2)",
    );
  });
});

describe("drift / anomaly conditions", () => {
  it("types change thresholds as percent and z-scores raw", () => {
    assert.equal(thresholdToInput("latency_p90_ms", 0.25, "change"), "25");
    assert.equal(thresholdFromInput("latency_p90_ms", "-20", "change"), -0.2);
    assert.equal(thresholdToInput("error_rate", 3, "anomaly"), "3");
    assert.equal(thresholdFromInput("error_rate", "3", "anomaly"), 3);
  });

  it("signs drift / anomaly thresholds by direction", () => {
    assert.equal(signedThreshold("change", "lt", 0.2), -0.2);
    assert.equal(signedThreshold("change", "gt", -0.2), 0.2);
    assert.equal(signedThreshold("anomaly", "abs", -3), 3);
    assert.equal(signedThreshold("threshold", "lt", 5), 5);
  });

  it("picks defaults per condition", () => {
    assert.deepEqual(conditionDefaults("score_mean", "change"), { operator: "lt", threshold: -0.2 });
    assert.deepEqual(conditionDefaults("cost_usd", "change"), { operator: "gt", threshold: 0.2 });
    assert.deepEqual(conditionDefaults("cost_usd", "anomaly"), { operator: "abs", threshold: 3 });
    assert.equal(conditionDefaults("error_rate", "threshold").threshold, 0.05);
  });

  it("formats the compared value and the reading", () => {
    assert.equal(formatRuleValue({ metric: "score_mean", condition: "change" }, -0.236), "-23.6%");
    assert.equal(formatRuleValue({ metric: "latency_p90_ms", condition: "anomaly" }, 4.21), "z=+4.2");
    assert.equal(formatRuleValue({ metric: "error_rate" }, 0.1), "10.0%");
    assert.equal(
      describeReading({
        metric: "score_mean",
        condition: "change",
        last_value: -0.25,
        last_observed: 0.6,
        last_baseline: 0.8,
      }),
      "0.600 vs 0.800 baseline (-25.0%)",
    );
    assert.equal(describeReading({ metric: "error_rate", last_value: 0.1 }), null);
  });

  it("describes change and anomaly rules", () => {
    const base = { score_name: null, score_source: null, window_minutes: 60 };
    assert.equal(
      describeRule({
        ...base,
        metric: "score_mean",
        score_name: "groundedness",
        operator: "lt",
        threshold: -0.2,
        condition: "change",
        baseline_minutes: 10080,
      }),
      "groundedness mean drops more than 20.0% over 1 hour vs the previous 7 days",
    );
    assert.equal(
      describeRule({
        ...base,
        metric: "latency_p90_ms",
        operator: "abs",
        threshold: 3,
        condition: "anomaly",
        baseline_minutes: 1440,
      }),
      "latency p90 more than 3.0σ away from the last 24 windows of 1 hour",
    );
  });
});
