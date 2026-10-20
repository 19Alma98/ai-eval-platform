import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { MetricMonitor } from "@/lib/api/types";
import {
  alarmState,
  latestFailRate,
  metricKey,
  MIN_ALARM_SAMPLES,
  parseAlarmThresholds,
} from "./alarms";

function metric(
  failRate: number | null,
  buckets: [number, number | null][],
  n = 10,
): MetricMonitor {
  return {
    name: "groundedness",
    source: "judge",
    n,
    mean: 0.8,
    fail_rate: failRate,
    threshold: 0.7,
    histogram_edges: [],
    histogram_counts: [],
    series: buckets.map(([count, rate], i) => ({
      bucket_start: `2026-01-01T00:0${i}:00Z`,
      n: count,
      mean: null,
      fail_rate: rate,
    })),
  };
}

describe("alarms", () => {
  it("parses stored thresholds defensively", () => {
    assert.deepEqual(parseAlarmThresholds('{"judge:a": 0.1, "b": 5, "c": "x"}'), {
      "judge:a": 0.1,
    });
    assert.deepEqual(parseAlarmThresholds("not json"), {});
    assert.deepEqual(parseAlarmThresholds(null), {});
  });

  it("reads the latest bucket with enough samples", () => {
    assert.equal(
      latestFailRate(metric(0.1, [[MIN_ALARM_SAMPLES, 0.5], [0, null]])),
      0.5,
    );
    assert.equal(latestFailRate(metric(0.1, [[4, 0.5], [0, null]])), null);
    assert.equal(latestFailRate(metric(0.1, [[0, null]])), null);
  });

  it("does not fire on tiny samples", () => {
    const tiny = metric(0.25, [[4, 0.25]], 4);
    assert.equal(alarmState(tiny, {}).firing, false);
  });

  it("fires on the window or the latest bucket when n is enough", () => {
    const m = metric(0.1, [[MIN_ALARM_SAMPLES, 0], [MIN_ALARM_SAMPLES, 0.5]]);
    assert.equal(alarmState(m, {}).firing, true);
    assert.equal(alarmState(m, { [metricKey(m)]: 0.6 }).firing, false);
    assert.equal(
      alarmState(metric(0.05, [[MIN_ALARM_SAMPLES, 0.05]]), {}).firing,
      false,
    );
    assert.equal(
      alarmState(metric(0.25, [[MIN_ALARM_SAMPLES, 0.25]], MIN_ALARM_SAMPLES), {}).firing,
      true,
    );
  });
});
