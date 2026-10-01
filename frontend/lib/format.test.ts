import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatDurationMs } from "./format";

describe("formatDurationMs", () => {
  it("formats milliseconds", () => {
    assert.equal(formatDurationMs(1250), "1.25s");
    assert.equal(formatDurationMs(40), "40ms");
  });
});
