import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { EvaluatorSummary } from "@/lib/api/types";
import { tallyTargets, targetState } from "./metric-target";

function row(status: string): EvaluatorSummary {
  return {
    evaluator_id: status,
    evaluator_name: status,
    run_id: status,
    status,
    n_items: 1,
    n_scored: 1,
    n_error: 0,
    n_skipped: 0,
    mean_score: 1,
    pass_rate: 1,
  };
}

describe("targetState", () => {
  it("maps summary statuses", () => {
    assert.equal(targetState("Passed"), "met");
    assert.equal(targetState("failed"), "missed");
    assert.equal(targetState("running"), "unknown");
    assert.equal(targetState(null), "unknown");
  });
});

describe("tallyTargets", () => {
  it("counts met and missed metrics", () => {
    assert.deepEqual(tallyTargets([row("passed"), row("failed"), row("running")]), {
      met: 1,
      missed: 1,
      total: 3,
    });
  });
});
