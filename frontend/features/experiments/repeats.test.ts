import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { EvaluationResult, ExperimentItemOutput } from "@/lib/api/types";
import { collapseResultsByItem, firstOutputByItem, repeatStatsOf } from "./repeats";

function result(
  item: string,
  repeat: number,
  score: number | null,
  label: string,
): EvaluationResult {
  return {
    id: `${item}-${repeat}`,
    run_id: "run",
    dataset_item_id: item,
    score,
    label,
    explanation: null,
    metadata: {},
    duration_ms: null,
    repeat,
  };
}

describe("collapseResultsByItem", () => {
  it("keeps single results as-is", () => {
    const single = result("a", 0, 1, "PASS");
    assert.equal(collapseResultsByItem([single]).get("a"), single);
  });

  it("averages repeats and flags flaky items", () => {
    const collapsed = collapseResultsByItem([
      result("a", 0, 1, "PASS"),
      result("a", 1, 0, "FAIL"),
      result("a", 2, 1, "PASS"),
    ]).get("a");
    assert.ok(collapsed);
    assert.equal(collapsed.score, 2 / 3);
    assert.equal(collapsed.label, "PASS");
    assert.equal(collapsed.id, "a-1");
    assert.deepEqual(repeatStatsOf(collapsed.metadata), { n: 3, passRate: 2 / 3, flaky: true });
  });

  it("ignores skipped repeats", () => {
    const collapsed = collapseResultsByItem([
      result("a", 0, null, "SKIPPED"),
      result("a", 1, 0, "FAIL"),
    ]).get("a");
    assert.equal(collapsed?.label, "FAIL");
    assert.equal(repeatStatsOf(collapsed?.metadata)?.flaky, false);
  });
});

describe("firstOutputByItem", () => {
  it("picks repeat 0", () => {
    const out = (repeat: number): ExperimentItemOutput => ({
      id: `o${repeat}`,
      experiment_id: "e",
      dataset_item_id: "a",
      actual_output: `r${repeat}`,
      context: null,
      metadata: {},
      updated_at: "",
      repeat,
    });
    assert.equal(firstOutputByItem([out(2), out(0), out(1)]).get("a")?.id, "o0");
  });
});

describe("repeatStatsOf", () => {
  it("reads the server's snake_case shape", () => {
    assert.deepEqual(repeatStatsOf({ repeats: { n: 2, pass_rate: 0.5, flaky: true } }), {
      n: 2,
      passRate: 0.5,
      flaky: true,
    });
    assert.equal(repeatStatsOf({}), null);
  });
});
