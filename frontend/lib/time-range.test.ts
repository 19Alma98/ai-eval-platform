import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  fromDatetimeLocalValue,
  isPreset,
  parseTimeRangeParams,
  previousPeriod,
  rangeFromPreset,
  toDatetimeLocalValue,
  writeTimeRangeParams,
} from "./time-range";

describe("rangeFromPreset", () => {
  it("returns ~60 minutes for 1h", () => {
    const now = new Date("2026-10-01T12:00:00.000Z");
    const { start, end } = rangeFromPreset("1h", now);
    assert.equal(end.toISOString(), now.toISOString());
    assert.equal(start.toISOString(), "2026-10-01T11:00:00.000Z");
  });
});

describe("previousPeriod", () => {
  it("shifts the window back by its duration", () => {
    const start = new Date("2026-10-01T10:00:00.000Z");
    const end = new Date("2026-10-01T12:00:00.000Z");
    const prev = previousPeriod(start, end);
    assert.equal(prev.start.toISOString(), "2026-10-01T08:00:00.000Z");
    assert.equal(prev.end.toISOString(), "2026-10-01T10:00:00.000Z");
  });
});

describe("parseTimeRangeParams / writeTimeRangeParams", () => {
  it("reads a preset", () => {
    const params = new URLSearchParams("range=6h");
    const win = parseTimeRangeParams(params, {
      defaultPreset: "24h",
      anchor: new Date("2026-10-01T12:00:00.000Z"),
    });
    assert.equal(win.kind, "6h");
    assert.equal(win.start.toISOString(), "2026-10-01T06:00:00.000Z");
  });

  it("reads a custom window", () => {
    const params = new URLSearchParams(
      "range=custom&since=2026-10-01T00:00:00.000Z&until=2026-10-01T03:00:00.000Z",
    );
    const win = parseTimeRangeParams(params, { defaultPreset: "24h" });
    assert.equal(win.kind, "custom");
    assert.equal(win.start.toISOString(), "2026-10-01T00:00:00.000Z");
    assert.equal(win.end.toISOString(), "2026-10-01T03:00:00.000Z");
  });

  it("falls back when custom bounds are invalid", () => {
    const params = new URLSearchParams("range=custom&since=bad&until=also-bad");
    const win = parseTimeRangeParams(params, {
      defaultPreset: "1h",
      anchor: new Date("2026-10-01T12:00:00.000Z"),
    });
    assert.equal(win.kind, "1h");
  });

  it("writes preset and clears since/until", () => {
    const params = new URLSearchParams("range=custom&since=x&until=y");
    writeTimeRangeParams(params, rangeFromPreset("24h", new Date("2026-10-01T12:00:00.000Z")));
    assert.equal(params.get("range"), "24h");
    assert.equal(params.get("since"), null);
    assert.equal(params.get("until"), null);
  });

  it("writes custom since/until", () => {
    const params = new URLSearchParams();
    writeTimeRangeParams(params, {
      kind: "custom",
      start: new Date("2026-10-01T00:00:00.000Z"),
      end: new Date("2026-10-01T02:00:00.000Z"),
    });
    assert.equal(params.get("range"), "custom");
    assert.equal(params.get("since"), "2026-10-01T00:00:00.000Z");
    assert.equal(params.get("until"), "2026-10-01T02:00:00.000Z");
  });
});

describe("isPreset", () => {
  it("accepts known presets only", () => {
    assert.equal(isPreset("24h"), true);
    assert.equal(isPreset("custom"), false);
    assert.equal(isPreset(null), false);
  });
});

describe("datetime-local roundtrip in UTC", () => {
  it("formats and parses wall time in UTC", () => {
    const d = new Date("2026-10-01T14:30:00.000Z");
    const local = toDatetimeLocalValue(d, "UTC");
    assert.equal(local, "2026-10-01T14:30");
    const back = fromDatetimeLocalValue(local, "UTC");
    assert.ok(back);
    assert.equal(back.toISOString(), "2026-10-01T14:30:00.000Z");
  });
});
