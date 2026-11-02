import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Experiment } from "@/lib/api/types";
import {
  chartMetrics,
  colorByOptions,
  defaultTradeoffAxes,
  formatChartValue,
  paretoFront,
  parseColorBy,
  timeSeriesData,
  tradeoffData,
  type ChartPoint,
} from "./experiment-charts";
import type { MatrixRow, MetricColumn } from "./experiment-matrix";

function row(
  id: string,
  created: string,
  metrics: Record<string, number | null>,
  extra: Partial<MatrixRow> = {},
): MatrixRow {
  return {
    experiment: { id, name: id, created_at: created } as Experiment,
    label: id,
    model: null,
    prompt: null,
    params: {},
    metrics: Object.fromEntries(
      Object.entries(metrics).map(([k, v]) => [k, { mean: v, passRate: null, nScored: 1 }]),
    ),
    ...extra,
  };
}

const COLUMNS: MetricColumn[] = [
  { key: "groundedness", label: "groundedness", kind: "evaluator" },
  { key: "logged:cost_usd", label: "cost_usd", kind: "logged" },
  { key: "logged:opengrade.latency_p95_ms", label: "opengrade.latency_p95_ms", kind: "logged" },
];

describe("chartMetrics", () => {
  it("labels SDK run metrics and marks lower-is-better", () => {
    const metrics = chartMetrics(COLUMNS);
    assert.deepEqual(
      metrics.map((m) => [m.key, m.label, m.lowerIsBetter]),
      [
        ["groundedness", "Groundedness", false],
        ["logged:cost_usd", "cost_usd", true],
        ["logged:opengrade.latency_p95_ms", "Latency p95", true],
      ],
    );
  });

  it("formats values per metric kind", () => {
    const [quality, , latency] = chartMetrics(COLUMNS);
    assert.equal(formatChartValue(quality, 0.8123), "0.81");
    assert.equal(formatChartValue(latency, 1500), "1.50s");
  });
});

describe("defaultTradeoffAxes", () => {
  it("puts quality against cost first", () => {
    assert.deepEqual(defaultTradeoffAxes(chartMetrics(COLUMNS)), {
      x: "logged:cost_usd",
      y: "groundedness",
    });
  });

  it("falls back to a second evaluator", () => {
    const metrics = chartMetrics([
      { key: "hit_at_k", label: "hit_at_k", kind: "evaluator" },
      { key: "mrr", label: "mrr", kind: "evaluator" },
    ]);
    assert.deepEqual(defaultTradeoffAxes(metrics), { x: "mrr", y: "hit_at_k" });
  });
});

describe("series data", () => {
  const rows = [
    row("b", "2026-02-01T00:00:00Z", { groundedness: 0.9, "logged:cost_usd": 2 }, { model: "big" }),
    row("a", "2026-01-01T00:00:00Z", { groundedness: 0.7, "logged:cost_usd": 1 }, { model: "small" }),
    row("c", "2026-03-01T00:00:00Z", { groundedness: null, "logged:cost_usd": 3 }),
  ];

  it("orders time points by creation and skips missing values", () => {
    const data = timeSeriesData(rows, "groundedness", "model");
    assert.deepEqual(
      data.points.map((p) => [p.id, p.series, p.y]),
      [
        ["a", "small", 0.7],
        ["b", "big", 0.9],
      ],
    );
    assert.deepEqual(data.series, ["big", "small"]);
    assert.equal(data.points[0].x, Date.parse("2026-01-01T00:00:00Z"));
  });

  it("builds trade-off points from two metrics", () => {
    const data = tradeoffData(rows, "logged:cost_usd", "groundedness", "none");
    assert.deepEqual(
      data.points.map((p) => [p.id, p.x, p.y]),
      [
        ["a", 1, 0.7],
        ["b", 2, 0.9],
      ],
    );
    assert.deepEqual(data.series, ["Experiments"]);
  });

  it("groups by a varying parameter, unset values last", () => {
    const withParams = [
      row("x", "2026-01-01T00:00:00Z", { groundedness: 0.5 }, { params: { top_k: "5" } }),
      row("y", "2026-01-02T00:00:00Z", { groundedness: 0.6 }),
    ];
    const data = timeSeriesData(withParams, "groundedness", "param:top_k");
    assert.deepEqual(data.series, ["5", "(not set)"]);
  });
});

describe("paretoFront", () => {
  const p = (id: string, x: number, y: number): ChartPoint => ({ id, name: id, series: "s", x, y });

  it("keeps points nothing beats on both axes (low cost, high quality)", () => {
    const points = [p("cheap", 1, 0.6), p("mid", 2, 0.8), p("worse", 3, 0.7), p("best", 4, 0.9)];
    assert.deepEqual(
      paretoFront(points, true, false).map((q) => q.id),
      ["cheap", "mid", "best"],
    );
  });

  it("handles two higher-is-better axes and ties", () => {
    const points = [p("a", 0.5, 0.5), p("b", 0.5, 0.5), p("c", 0.9, 0.4), p("d", 0.4, 0.4)];
    assert.deepEqual(
      paretoFront(points, false, false).map((q) => q.id),
      ["a", "b", "c"],
    );
  });
});

describe("color by", () => {
  const varying = { top_k: ["3", "5"], sweep: ["s1"] };

  it("lists model, prompt and varying params", () => {
    assert.deepEqual(
      colorByOptions(varying).map((o) => o.value),
      ["none", "model", "prompt", "param:sweep", "param:top_k"],
    );
  });

  it("parses only known values", () => {
    assert.equal(parseColorBy("param:top_k", varying), "param:top_k");
    assert.equal(parseColorBy("param:gone", varying), "none");
    assert.equal(parseColorBy("model", varying), "model");
    assert.equal(parseColorBy(null, varying), "none");
  });
});
