import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Experiment, ExperimentSummary } from "@/lib/api/types";
import {
  bestByColumn,
  buildMatrix,
  columnDecimals,
  filterRows,
  flattenParams,
  paramDiff,
  sortRows,
  trendSeries,
  varyingParams,
  type MatrixRow,
} from "./experiment-matrix";

function exp(id: string, created: string, modelConfig: Record<string, unknown>): Experiment {
  return {
    id,
    project_id: "p",
    name: `exp-${id}`,
    dataset_id: id === "c" ? "ds2" : "ds1",
    model_config: modelConfig,
    app_config_id: null,
    version: id === "a" ? "v1" : null,
    baseline_experiment_id: null,
    metrics_set_id: null,
    status: "completed",
    created_at: created,
  };
}

function summary(id: string, scores: Record<string, number | null>): ExperimentSummary {
  return {
    experiment_id: id,
    evaluators: Object.entries(scores).map(([name, mean]) => ({
      evaluator_id: `${name}-id`,
      evaluator_name: name,
      run_id: `${id}-${name}`,
      status: "completed",
      n_items: 4,
      n_scored: 4,
      n_error: 0,
      n_skipped: 0,
      mean_score: mean,
      pass_rate: mean,
    })),
    experiment_metrics: id === "b" ? { latency_p50: 120 } : {},
  };
}

const experiments = [
  exp("a", "2026-01-01T00:00:00Z", { model: "gpt-4o", prompt_version: 1, temperature: 0 }),
  exp("b", "2026-01-02T00:00:00Z", { model: "gpt-4o-mini", prompt_version: 2, temperature: 0 }),
  exp("c", "2026-01-03T00:00:00Z", { model: "gpt-4o", prompt: { name: "rag", version: 3 } }),
];
const summaries = [
  summary("a", { groundedness: 0.7, recall_at_k: 0.5 }),
  summary("b", { groundedness: 0.9 }),
  summary("c", { groundedness: null, recall_at_k: 0.8 }),
];

describe("experiment matrix", () => {
  const { rows, columns } = buildMatrix(experiments, summaries);

  it("builds one column per metric, logged metrics last", () => {
    assert.deepEqual(
      columns.map((c) => c.key),
      ["groundedness", "recall_at_k", "logged:latency_p50"],
    );
    assert.equal(rows[0].label, "v1");
    assert.equal(rows[2].prompt, "rag@3");
    assert.equal(rows[1].prompt, "v2");
    assert.equal(rows[0].metrics.groundedness.mean, 0.7);
  });

  it("sorts by metric with missing values last", () => {
    const desc = sortRows(rows, { key: "groundedness", dir: "desc" });
    assert.deepEqual(desc.map((r) => r.experiment.id), ["b", "a", "c"]);
    const asc = sortRows(rows, { key: "groundedness", dir: "asc" });
    assert.deepEqual(asc.map((r) => r.experiment.id), ["a", "b", "c"]);
  });

  it("filters by model, prompt, dataset and param", () => {
    assert.deepEqual(
      filterRows(rows, { model: "gpt-4o" }).map((r) => r.experiment.id),
      ["a", "c"],
    );
    assert.deepEqual(filterRows(rows, { datasetId: "ds2" }).map((r) => r.experiment.id), ["c"]);
    assert.deepEqual(
      filterRows(rows, { param: { key: "prompt_version", value: "2" } }).map(
        (r) => r.experiment.id,
      ),
      ["b"],
    );
  });

  it("keeps only parameters that vary", () => {
    const varying = varyingParams(rows);
    assert.deepEqual(varying.model, ["gpt-4o", "gpt-4o-mini"]);
    assert.ok("temperature" in varying, "missing on one row counts as varying");
    assert.deepEqual(flattenParams({ a: { b: 1 }, content_hash: "x" }), { "a.b": "1" });
  });

  it("marks the best value and orders the trend by creation", () => {
    assert.deepEqual(bestByColumn(rows, columns), {
      groundedness: 0.9,
      recall_at_k: 0.8,
      "logged:latency_p50": 120,
    });
    assert.deepEqual(
      trendSeries(rows, columns).map((p) => [p.label, p.groundedness]),
      [
        ["v1", 0.7],
        ["exp-b", 0.9],
        ["exp-c", null],
      ],
    );
  });

  it("picks the lowest latency when several logged values exist", () => {
    const withLatency = [
      exp("a", "2026-01-01T00:00:00Z", { model: "a" }),
      exp("b", "2026-01-02T00:00:00Z", { model: "b" }),
    ];
    const latencySummaries: ExperimentSummary[] = [
      {
        experiment_id: "a",
        evaluators: [],
        experiment_metrics: { latency_p50_ms: 200 },
      },
      {
        experiment_id: "b",
        evaluators: [],
        experiment_metrics: { latency_p50_ms: 80 },
      },
    ];
    const built = buildMatrix(withLatency, latencySummaries);
    assert.deepEqual(bestByColumn(built.rows, built.columns), {
      "logged:latency_p50_ms": 80,
    });
  });

  it("diffs only params that differ between configs", () => {
    assert.deepEqual(
      paramDiff(
        { model: { name: "gpt-4o", temperature: 0.2 }, content_hash: "x" },
        { model: { name: "gpt-4o", temperature: 0 }, content_hash: "y" },
      ),
      [{ key: "model.temperature", candidate: "0.2", baseline: "0" }],
    );
  });
});

describe("columnDecimals", () => {
  const rows = (values: (number | null)[]): MatrixRow[] =>
    values.map(
      (mean) =>
        ({ metrics: { m: { mean, passRate: null, nScored: 1 } } }) as unknown as MatrixRow,
    );
  const logged = { key: "m", label: "m", kind: "logged" } as const;

  it("uses one precision per column", () => {
    assert.equal(columnDecimals(rows([1200, 980]), logged), 0);
    assert.equal(columnDecimals(rows([812.5, 1204.25]), logged), 0);
    assert.equal(columnDecimals(rows([0.5, 1.2345]), logged), 2);
    assert.equal(columnDecimals(rows([0.0012, 0.0004, null]), logged), 4);
  });

  it("keeps two decimals for judge scores", () => {
    assert.equal(columnDecimals(rows([0.5]), { key: "m", label: "m", kind: "evaluator" }), 2);
  });
});
