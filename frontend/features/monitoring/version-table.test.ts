import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { VersionSummary } from "@/lib/api/types";
import { versionFailRate, versionMetricColumns, worstIndex } from "./version-table";

function row(version: string, metrics: VersionSummary["metrics"]): VersionSummary {
  return {
    version,
    n_traces: 10,
    n_errors: 0,
    error_rate: 0,
    latency: { p50_ms: null, p90_ms: null, p99_ms: null },
    total_tokens: 0,
    cost_usd: 0,
    cost_per_trace_usd: null,
    traces_truncated: false,
    metrics,
  };
}

describe("versionMetricColumns", () => {
  it("keeps the metrics with the most samples", () => {
    const rows = [
      row("v1", [
        { name: "groundedness", source: "judge", n: 50, mean: 0.8, fail_rate: 0.1 },
        { name: "user_feedback", source: "human", n: 3, mean: 1, fail_rate: 0 },
      ]),
      row("v2", [{ name: "groundedness", source: "judge", n: 40, mean: 0.6, fail_rate: 0.3 }]),
    ];
    const cols = versionMetricColumns(rows, 1);
    assert.deepEqual(cols, [{ key: "judge:groundedness", name: "groundedness", source: "judge" }]);
    assert.equal(versionFailRate(rows[1], cols[0]), 0.3);
  });
});

describe("worstIndex", () => {
  it("flags the highest value only when versions differ", () => {
    assert.equal(worstIndex([0.1, 0.3, null]), 1);
    assert.equal(worstIndex([0.2, 0.2]), null);
    assert.equal(worstIndex([0.2]), null);
  });
});
