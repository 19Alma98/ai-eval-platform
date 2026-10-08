import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatStatusLabel, statusTone } from "./status-badge";

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

  it("maps insufficient_n to warn", () => {
    assert.equal(statusTone("insufficient_n"), "warn");
  });

  it("falls back to unset", () => {
    assert.equal(statusTone("PENDING"), "unset");
  });
});

describe("formatStatusLabel", () => {
  it("maps known statuses to readable English labels", () => {
    assert.equal(formatStatusLabel("completed"), "Completed");
    assert.equal(formatStatusLabel("PENDING"), "Pending");
    assert.equal(formatStatusLabel("failed"), "Failed");
    assert.equal(formatStatusLabel("ERROR"), "Error");
    assert.equal(formatStatusLabel("skipped"), "Skipped");
    assert.equal(formatStatusLabel("regression"), "Regression");
    assert.equal(formatStatusLabel("improved"), "Improved");
    assert.equal(formatStatusLabel("unchanged"), "Unchanged");
    assert.equal(formatStatusLabel("unavailable"), "Unavailable");
    assert.equal(formatStatusLabel("insufficient_n"), "Insufficient n");
    assert.equal(formatStatusLabel("pass"), "Passed");
    assert.equal(formatStatusLabel("passed"), "Passed");
    assert.equal(formatStatusLabel("unset"), "Unset");
  });

  it("capitalizes unknown statuses", () => {
    assert.equal(formatStatusLabel("running"), "Running");
  });
});
