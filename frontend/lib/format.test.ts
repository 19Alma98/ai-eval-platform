import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatDurationMs, resolveLabel } from "./format";

describe("formatDurationMs", () => {
  it("formats milliseconds", () => {
    assert.equal(formatDurationMs(1250), "1.25s");
    assert.equal(formatDurationMs(40), "40ms");
  });
});

describe("resolveLabel", () => {
  it("returns looked-up name when present", () => {
    const map = new Map([["id-1", "Exact match"]]);
    assert.equal(resolveLabel("id-1", map), "Exact match");
  });

  it("trims looked-up names", () => {
    const map = new Map([["id-1", "  Exact  "]]);
    assert.equal(resolveLabel("id-1", map), "Exact");
  });

  it("uses human fallback when id missing from map", () => {
    assert.equal(resolveLabel("missing", new Map()), "Unknown");
    assert.equal(
      resolveLabel("missing", new Map(), "Unknown dataset"),
      "Unknown dataset",
    );
  });

  it("uses fallback when id is nullish", () => {
    assert.equal(resolveLabel(null, new Map([["a", "A"]])), "Unknown");
    assert.equal(resolveLabel(undefined), "Unknown");
  });
});
