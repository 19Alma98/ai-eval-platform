import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatConfigValue } from "./format-config-value";

describe("formatConfigValue", () => {
  it("unwraps a single string field (prompt.system)", () => {
    assert.equal(
      formatConfigValue({ system: "Be concise." }),
      "Be concise.",
    );
  });

  it("unwraps model_id to plain text", () => {
    assert.equal(formatConfigValue({ model_id: "gpt-demo" }), "gpt-demo");
  });

  it("formats scalar key-value pairs without JSON braces", () => {
    assert.equal(formatConfigValue({ top_k: 2 }), "top_k: 2");
  });

  it("handles empty and null", () => {
    assert.equal(formatConfigValue({}), "—");
    assert.equal(formatConfigValue(null), "—");
  });
});
