import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deltaTone, isLowerBetter } from "./metric-direction";

describe("isLowerBetter", () => {
  it("matches latency and cost prefixes and ms/usd suffixes", () => {
    assert.equal(isLowerBetter("latency"), true);
    assert.equal(isLowerBetter("latency_p50_ms"), true);
    assert.equal(isLowerBetter("cost_usd"), true);
    assert.equal(isLowerBetter("Cost"), true);
    assert.equal(isLowerBetter("opengrade.latency_p95_ms"), true);
    assert.equal(isLowerBetter("tokens_ms"), true);
    assert.equal(isLowerBetter("price_usd"), true);
  });

  it("strips the matrix logged: prefix", () => {
    assert.equal(isLowerBetter("logged:latency_p50"), true);
    assert.equal(isLowerBetter("logged:cost_usd"), true);
  });

  it("leaves quality metrics as higher-is-better", () => {
    assert.equal(isLowerBetter("groundedness"), false);
    assert.equal(isLowerBetter("hit_at_k"), false);
    assert.equal(isLowerBetter("correctness"), false);
  });
});

describe("deltaTone", () => {
  it("treats lower deltas as better when lowerIsBetter", () => {
    assert.equal(deltaTone(-10, true), "better");
    assert.equal(deltaTone(10, true), "worse");
    assert.equal(deltaTone(0.05, false), "better");
    assert.equal(deltaTone(-0.05, false), "worse");
    assert.equal(deltaTone(0, true), "neutral");
    assert.equal(deltaTone(null, false), "neutral");
  });
});
