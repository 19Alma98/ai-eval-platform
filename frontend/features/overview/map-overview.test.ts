import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ProjectOverview } from "@/lib/api/types";
import {
  buildLivePanel,
  buildReleasePanel,
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

  it("merges firing metric alarms with a monitoring href", () => {
    const rows = mergeAttentionItems(emptyOverview, {
      metrics: [
        {
          name: "user_feedback",
          source: "human",
          n: 12,
          mean: null,
          fail_rate: 0.25,
          threshold: null,
          histogram_edges: [],
          histogram_counts: [],
          series: [{ bucket_start: "2026-01-01T00:00:00Z", n: 12, mean: null, fail_rate: 0.25 }],
        },
        {
          name: "groundedness",
          source: "judge",
          n: 4,
          mean: 0.5,
          fail_rate: 0.25,
          threshold: 0.7,
          histogram_edges: [],
          histogram_counts: [],
          series: [{ bucket_start: "2026-01-01T00:00:00Z", n: 4, mean: 0.5, fail_rate: 0.25 }],
        },
      ],
    });
    const alarms = rows.filter((r) => r.kind === "metric_alarm");
    assert.equal(alarms.length, 1);
    assert.match(alarms[0]!.title, /user_feedback/i);
    assert.equal(alarms[0]!.href, "/monitoring");
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

describe("buildReleasePanel", () => {
  it("asks for a test set first when nothing exists", () => {
    const panel = buildReleasePanel(emptyOverview);
    assert.equal(panel.headline, "No experiments yet");
    assert.equal(panel.tone, "neutral");
    assert.deepEqual(panel.primary, { label: "Create test set", href: "/datasets" });
  });

  it("leads with regressions and links to the comparison", () => {
    const panel = buildReleasePanel({
      ...emptyOverview,
      offline: {
        ...emptyOverview.offline,
        n_datasets: 1,
        release_ready: true,
        latest_experiment: {
          id: "c1",
          name: "candidate",
          status: "finished",
          created_at: "2026-01-01T00:00:00Z",
          baseline_experiment_id: "b1",
        },
        compare: {
          candidate_experiment_id: "c1",
          baseline_experiment_id: "b1",
          metrics: [
            { name: "must_contain", metric: "pass_rate", candidate: 0.4, baseline: 1, delta: -0.6, status: "regressed" },
            { name: "groundedness", metric: "pass_rate", candidate: 0.8, baseline: 0.5, delta: 0.3, status: "improved" },
            { name: "groundedness", metric: "mean_score", candidate: 0.8, baseline: 0.5, delta: 0.3, status: "improved" },
          ],
        },
        regressions: [{ name: "must_contain", delta: -0.6, status: "regressed" }],
      },
    });
    assert.equal(panel.headline, "1 metric got worse");
    assert.equal(panel.tone, "fail");
    assert.equal(panel.detail, "candidate vs its baseline: 1 better, 1 worse, 0 unchanged.");
    assert.equal(panel.primary?.href, "/experiments/c1/compare?baseline=b1");
    assert.equal(panel.secondary?.href, "/release");
    assert.equal(panel.stats[0].value, "60%");
  });
});

describe("buildLivePanel", () => {
  it("explains an empty range", () => {
    const panel = buildLivePanel(emptyOverview, "24h");
    assert.equal(panel.headline, "No live traffic");
    assert.match(panel.detail, /last 24 hours/);
  });

  it("reports the failing share", () => {
    const panel = buildLivePanel(
      {
        ...emptyOverview,
        live: { ...emptyOverview.live, n_interactions: 4, n_failed: 3, fail_rate: 0.75, mean_score: 0.5 },
      },
      "1h",
    );
    assert.equal(panel.headline, "75% of answers failing");
    assert.equal(panel.tone, "fail");
    assert.equal(panel.primary?.href, "/live-runs?failed=1");
  });
});
