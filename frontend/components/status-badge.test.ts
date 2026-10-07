import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { statusTone } from "./status-badge";

describe("statusTone", () => {
  it("maps pass labels to ok", () => {
    assert.equal(statusTone("PASS"), "ok");
    assert.equal(statusTone("PASSED"), "ok");
  });

  it("maps fail labels to fail", () => {
    assert.equal(statusTone("FAIL"), "fail");
    assert.equal(statusTone("FAILED"), "fail");
  });

  it("maps ERROR to error", () => {
    assert.equal(statusTone("ERROR"), "error");
  });

  it("maps SKIPPED to warn", () => {
    assert.equal(statusTone("SKIPPED"), "warn");
  });

  it("falls back to unset", () => {
    assert.equal(statusTone("PENDING"), "unset");
  });
});
