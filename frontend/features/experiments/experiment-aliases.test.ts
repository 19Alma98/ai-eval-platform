import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExperimentAlias } from "@/lib/api/types";
import {
  MAIN_ALIAS,
  aliasesByExperimentId,
  aliasTargetId,
  defaultBaselineFromMainAlias,
  isExamMismatchError,
  isExperimentPromotable,
} from "./experiment-aliases";

function alias(
  name: string,
  experimentId: string,
  datasetId = "ds-1",
): ExperimentAlias {
  return {
    name,
    experiment_id: experimentId,
    updated_at: "2026-01-01T00:00:00Z",
    experiment: {
      id: experimentId,
      name: `exp-${experimentId}`,
      version: null,
      dataset_id: datasetId,
      metrics_set_id: null,
      status: "completed",
      created_at: "2026-01-01T00:00:00Z",
    },
  };
}

describe("aliasesByExperimentId", () => {
  it("groups alias names under each experiment and puts main first", () => {
    const map = aliasesByExperimentId([
      alias("candidate", "e1"),
      alias("main", "e1"),
      alias("production", "e2"),
    ]);
    assert.deepEqual(map.get("e1"), ["main", "candidate"]);
    assert.deepEqual(map.get("e2"), ["production"]);
  });
});

describe("aliasTargetId", () => {
  it("returns the experiment id for a named alias", () => {
    const aliases = [alias("main", "e-main"), alias("production", "e-prod")];
    assert.equal(aliasTargetId(aliases, MAIN_ALIAS), "e-main");
    assert.equal(aliasTargetId(aliases, "missing"), null);
    assert.equal(aliasTargetId(aliases, "  "), null);
  });
});

describe("isExperimentPromotable", () => {
  it("rejects running, failed, and cancelled", () => {
    assert.equal(isExperimentPromotable("completed"), true);
    assert.equal(isExperimentPromotable("pending"), true);
    assert.equal(isExperimentPromotable("running"), false);
    assert.equal(isExperimentPromotable("failed"), false);
    assert.equal(isExperimentPromotable("cancelled"), false);
  });
});

describe("isExamMismatchError", () => {
  it("detects force / different dataset or metrics set messages", () => {
    assert.equal(
      isExamMismatchError(
        "Alias 'main' points to experiment x with a different dataset; pass force=true to move it anyway",
      ),
      true,
    );
    assert.equal(
      isExamMismatchError("Alias has a different metrics set"),
      true,
    );
    assert.equal(isExamMismatchError("Experiment is running"), false);
  });
});

describe("defaultBaselineFromMainAlias", () => {
  it("prefers query, then experiment baseline, then main on same dataset", () => {
    assert.equal(
      defaultBaselineFromMainAlias({
        baselineFromQuery: " from-q ",
        baselineExperimentId: "from-exp",
        mainTargetId: "from-main",
        candidateDatasetId: "ds-1",
        mainDatasetId: "ds-1",
      }),
      "from-q",
    );
    assert.equal(
      defaultBaselineFromMainAlias({
        baselineFromQuery: null,
        baselineExperimentId: "from-exp",
        mainTargetId: "from-main",
        candidateDatasetId: "ds-1",
        mainDatasetId: "ds-1",
      }),
      "from-exp",
    );
    assert.equal(
      defaultBaselineFromMainAlias({
        baselineFromQuery: null,
        baselineExperimentId: null,
        mainTargetId: "from-main",
        candidateDatasetId: "ds-1",
        mainDatasetId: "ds-1",
      }),
      "from-main",
    );
  });

  it("does not auto-pick main when datasets differ", () => {
    assert.equal(
      defaultBaselineFromMainAlias({
        baselineFromQuery: null,
        baselineExperimentId: null,
        mainTargetId: "from-main",
        candidateDatasetId: "ds-a",
        mainDatasetId: "ds-b",
      }),
      null,
    );
  });
});
