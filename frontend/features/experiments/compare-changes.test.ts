import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { relativeChange, runMetricChanges } from "./compare-changes";

describe("relativeChange", () => {
  it("is relative to the baseline magnitude", () => {
    assert.equal(relativeChange(110, 100), 0.1);
    assert.equal(relativeChange(-2, -4), 0.5);
    assert.equal(relativeChange(1, 0), null);
    assert.equal(relativeChange(null, 1), null);
  });
});

describe("runMetricChanges", () => {
  it("labels SDK metrics, puts them first and colors by direction", () => {
    const rows = runMetricChanges([
      { key: "cost_usd", candidate: 1.5, baseline: 1.0, delta: 0.5 },
      { key: "opengrade.latency_p95_ms", candidate: 800, baseline: 1000, delta: -200 },
      { key: "opengrade.error_rate", candidate: 0.1, baseline: 0.05, delta: 0.05 },
      { key: "answers", candidate: 3, baseline: null, delta: null },
    ]);
    assert.deepEqual(
      rows.map((r) => [r.label, r.change, r.tone]),
      [
        ["Errors", "+5.0 pts", "worse"],
        ["Latency p95", "−20%", "better"],
        ["answers", null, "neutral"],
        ["cost_usd", "+50%", "worse"],
      ],
    );
    assert.equal(rows[3].baseline, "1");
    assert.equal(rows[2].baseline, "—");
  });

  it("falls back to the absolute delta when the baseline is zero", () => {
    const [row] = runMetricChanges([{ key: "retries", candidate: 2, baseline: 0, delta: 2 }]);
    assert.equal(row.change, "+2");
    assert.equal(row.tone, "better");
  });

  it("uses one decimal for small relative changes", () => {
    const [row] = runMetricChanges([{ key: "cost_usd", candidate: 1.02, baseline: 1, delta: 0.02 }]);
    assert.equal(row.change, "+2.0%");
  });
});
