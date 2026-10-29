import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  describeRule,
  formatAlertValue,
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
