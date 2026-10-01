import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { rangeFromPreset } from "./time-range";

describe("rangeFromPreset", () => {
  it("returns ~60 minutes for 1h", () => {
    const now = new Date("2026-10-01T12:00:00.000Z");
    const { start, end } = rangeFromPreset("1h", now);
    assert.equal(end.toISOString(), now.toISOString());
    assert.equal(start.toISOString(), "2026-10-01T11:00:00.000Z");
  });
});
