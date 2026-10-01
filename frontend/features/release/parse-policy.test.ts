import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parsePolicyYaml } from "./parse-policy";

describe("parsePolicyYaml", () => {
  it("parses quality.min policy", () => {
    const p = parsePolicyYaml("quality:\n  min: 0.85\n");
    assert.equal((p as { quality: { min: number } }).quality.min, 0.85);
  });
  it("throws on invalid yaml", () => {
    assert.throws(() => parsePolicyYaml(":"));
  });
});
