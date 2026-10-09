import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { shouldShowLiveChart, mapPassRateBars } from "./map-overview";

describe("shouldShowLiveChart", () => {
  it("hides when fewer than 4 buckets with n>0", () => {
    assert.equal(
      shouldShowLiveChart([
        { bucket_start: "a", n: 1, mean_score: 0.5, fail_rate: 0 },
        { bucket_start: "b", n: 0, mean_score: null, fail_rate: null },
        { bucket_start: "c", n: 2, mean_score: 0.6, fail_rate: 0.1 },
      ]),
      false,
    );
  });
  it("shows when >=4 non-empty buckets", () => {
    const series = [1, 2, 3, 4].map((i) => ({
      bucket_start: String(i),
      n: 1,
      mean_score: 0.5,
      fail_rate: 0,
    }));
    assert.equal(shouldShowLiveChart(series), true);
  });
});

describe("mapPassRateBars", () => {
  it("returns null when compare is missing", () => {
    assert.equal(
      mapPassRateBars({
        generated_at: "2026-01-01T00:00:00Z",
        since: "2026-01-01T00:00:00Z",
        until: "2026-01-02T00:00:00Z",
        live: {
          n_interactions: 0,
          n_failed: 0,
          n_pending: 0,
          mean_score: null,
          fail_rate: null,
          series: [],
          attention: [],
        },
        offline: {
          n_datasets: 0,
          metrics_set: null,
          reference_threshold: null,
          latest_experiment: null,
          release_ready: false,
          compare: null,
          regressions: [],
        },
        calibration_alerts: [],
        warnings: [],
      }),
      null,
    );
  });
});
