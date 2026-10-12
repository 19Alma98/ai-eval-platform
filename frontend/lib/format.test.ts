import assert from "node:assert/strict";
import { describe, it, test } from "node:test";
import {
  formatDeltaPoints,
  formatDurationMs,
  formatPercent,
  formatScore,
  formatRelativeTime,
  parseTimestamp,
  resolveLabel,
} from "./format";

describe("formatDurationMs", () => {
  it("formats milliseconds", () => {
    assert.equal(formatDurationMs(1250), "1.25s");
    assert.equal(formatDurationMs(40), "40ms");
  });
});

describe("parseTimestamp", () => {
  it("treats naive ISO as UTC", () => {
    const d = parseTimestamp("2026-10-12T13:04:04.419268");
    assert.equal(d.toISOString(), "2026-10-12T13:04:04.419Z");
  });

  it("keeps explicit offsets", () => {
    const d = parseTimestamp("2026-10-12T13:04:04.419268Z");
    assert.equal(d.toISOString(), "2026-10-12T13:04:04.419Z");
  });
});

describe("formatRelativeTime", () => {
  it("uses whole hours without rounding up early", () => {
    const now = new Date("2026-10-12T16:05:00.000Z");
    const created = new Date("2026-10-12T14:55:00.000Z"); // 1h10m ago
    assert.equal(formatRelativeTime(created, now), "1 hour ago");
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

test("formatScore uses two decimals", () => {
  assert.equal(formatScore(0.70833), "0.71");
  assert.equal(formatScore(null), "—");
});

test("formatPercent drops needless decimals", () => {
  assert.equal(formatPercent(0.5), "50%");
  assert.equal(formatPercent(0.583333), "58.3%");
  assert.equal(formatPercent(undefined), "—");
});

test("formatDeltaPoints is signed", () => {
  assert.equal(formatDeltaPoints(-0.1667), "−17 pts");
  assert.equal(formatDeltaPoints(0.05), "+5 pts");
  assert.equal(formatDeltaPoints(0.001), "±0");
});
