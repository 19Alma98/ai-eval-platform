import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { sortMetricsForDisplay } from "./sort-metrics";

describe("sortMetricsForDisplay", () => {
  it("puts regressions first", () => {
    const out = sortMetricsForDisplay([
      { status: "improved" },
      { status: "regression" },
      { status: "unchanged" },
    ]);
    assert.equal(out[0].status, "regression");
  });

  it("ranks insufficient_n with other warn statuses after regression", () => {
    const out = sortMetricsForDisplay([
      { status: "improved" },
      { status: "insufficient_n" },
      { status: "regression" },
    ]);
    assert.equal(out[0].status, "regression");
    assert.equal(out[1].status, "insufficient_n");
    assert.equal(out[2].status, "improved");
  });
});
