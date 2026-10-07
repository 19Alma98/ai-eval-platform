import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { EvaluateResponse, EvaluationRun, Experiment } from "@/lib/api/types";
import { classifyEvaluateResponse } from "./evaluate-outcome";

function experiment(status: string): Experiment {
  return {
    id: "e1",
    project_id: "p1",
    name: "exp",
    dataset_id: "d1",
    model_config: {},
    app_config_id: null,
    version: null,
    baseline_experiment_id: null,
    metrics_set_id: null,
    status,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function run(
  status: string,
  results: EvaluationRun["results"] = [],
): EvaluationRun {
  return {
    id: "r1",
    experiment_id: "e1",
    evaluator_id: "ev1",
    status,
    started_at: null,
    finished_at: null,
    metadata: {},
    results,
  };
}

describe("classifyEvaluateResponse", () => {
  it("returns success when experiment and runs are ok", () => {
    const data: EvaluateResponse = {
      experiment: experiment("completed"),
      runs: [run("PASSED", [{ id: "x", run_id: "r1", dataset_item_id: "i1", score: 1, label: "PASS", explanation: null, metadata: {}, duration_ms: 1 }])],
    };
    assert.deepEqual(classifyEvaluateResponse(data), {
      kind: "success",
      errorCount: 0,
    });
  });

  it("returns with_errors when experiment status is failed", () => {
    const data: EvaluateResponse = {
      experiment: experiment("failed"),
      runs: [run("ERROR")],
    };
    assert.equal(classifyEvaluateResponse(data).kind, "with_errors");
  });

  it("counts ERROR item labels", () => {
    const data: EvaluateResponse = {
      experiment: experiment("completed"),
      runs: [
        run("PASSED", [
          {
            id: "a",
            run_id: "r1",
            dataset_item_id: "i1",
            score: null,
            label: "ERROR",
            explanation: "boom",
            metadata: {},
            duration_ms: 1,
          },
          {
            id: "b",
            run_id: "r1",
            dataset_item_id: "i2",
            score: 1,
            label: "PASS",
            explanation: null,
            metadata: {},
            duration_ms: 1,
          },
        ]),
      ],
    };
    assert.deepEqual(classifyEvaluateResponse(data), {
      kind: "with_errors",
      errorCount: 1,
    });
  });
});
