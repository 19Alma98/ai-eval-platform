import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ProjectOverview } from "@/lib/api/types";
import {
  shouldShowLiveChart,
  mapPassRateBars,
  mergeAttentionItems,
  overviewWarningMessages,
  regressionDrillDownHref,
} from "./map-overview";

const emptyOverview: ProjectOverview = {
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
};

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
    assert.equal(mapPassRateBars({ ...emptyOverview }), null);
  });
});

describe("regressionDrillDownHref", () => {
  it("uses compare route when baseline is known", () => {
    assert.equal(
      regressionDrillDownHref({
        ...emptyOverview.offline,
        compare: {
          candidate_experiment_id: "exp-c",
          baseline_experiment_id: "exp-b",
          metrics: [],
        },
      }),
      "/experiments/exp-c/compare?baseline=exp-b",
    );
  });

  it("falls back to latest experiment or list", () => {
    assert.equal(
      regressionDrillDownHref({
        ...emptyOverview.offline,
        latest_experiment: {
          id: "exp-latest",
          name: "Run",
          status: "completed",
          created_at: "2026-01-01T00:00:00Z",
          baseline_experiment_id: null,
        },
      }),
      "/experiments/exp-latest",
    );
    assert.equal(regressionDrillDownHref({ ...emptyOverview.offline }), "/experiments");
  });
});

describe("mergeAttentionItems", () => {
  it("adds href on regression rows", () => {
    const rows = mergeAttentionItems({
      ...emptyOverview,
      offline: {
        ...emptyOverview.offline,
        regressions: [{ name: "pass_rate", delta: -0.05, status: "worse" }],
        compare: {
          candidate_experiment_id: "c1",
          baseline_experiment_id: "b1",
          metrics: [],
        },
      },
    });
    const regression = rows.find((r) => r.kind === "regression");
    assert.equal(regression?.href, "/experiments/c1/compare?baseline=b1");
  });
});

describe("overviewWarningMessages", () => {
  it("maps known warning codes to user-facing copy", () => {
    const messages = overviewWarningMessages([
      "live_truncated",
      "calibration_unavailable",
    ]);
    assert.equal(messages.length, 2);
    assert.match(messages[0]!, /10,000/);
    assert.match(messages[1]!, /calibration/i);
  });
});
