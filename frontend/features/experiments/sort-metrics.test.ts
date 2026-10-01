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
});
