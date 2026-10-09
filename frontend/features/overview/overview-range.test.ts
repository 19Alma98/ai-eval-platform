import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseOverviewRangeParam } from "./overview-range";

describe("parseOverviewRangeParam", () => {
  it("defaults to 24h", () => {
    assert.equal(parseOverviewRangeParam(null), "24h");
    assert.equal(parseOverviewRangeParam("nope"), "24h");
  });
  it("accepts known presets", () => {
    assert.equal(parseOverviewRangeParam("1h"), "1h");
    assert.equal(parseOverviewRangeParam("7d"), "7d");
  });
});
