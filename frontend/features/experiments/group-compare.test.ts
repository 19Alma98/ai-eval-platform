import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DatasetItem, GroupCompare, MetricComparison } from "@/lib/api/types";
import { groupableMetadataKeys, groupCompareRows } from "./group-compare";

function item(metadata: Record<string, unknown>): DatasetItem {
  return {
    id: Math.random().toString(),
    dataset_id: "ds",
    input: "q",
    expected_output: null,
    actual_output: null,
    context: null,
    metadata,
    source_trace_id: null,
    source_span_id: null,
  };
}

function metric(status: string, delta: number): MetricComparison {
  return {
    evaluator_id: "e1",
    evaluator_name: "groundedness",
    metric: "mean_score",
    candidate: 0.5,
    baseline: 0.5 - delta,
    delta,
    status,
  } as MetricComparison;
}

describe("groupableMetadataKeys", () => {
  it("keeps scalar keys with several values, drops gold and constant keys", () => {
    const keys = groupableMetadataKeys([
      item({ category: "billing", lang: "it", expected_doc_ids: ["a"], nested: { x: 1 } }),
      item({ category: "shipping", lang: "it", tags: ["a", "b"] }),
    ]);
    assert.deepEqual(keys, ["category", "tags"]);
  });
});

describe("groupCompareRows", () => {
  it("puts groups with a regression first", () => {
    const groups: GroupCompare[] = [
      { value: "billing", n_items: 6, metrics: [metric("unchanged", 0)], n_regressions: 0 },
      { value: "shipping", n_items: 6, metrics: [metric("regression", -0.5)], n_regressions: 1 },
    ];
    const rows = groupCompareRows(groups);
    assert.deepEqual(
      rows.map((r) => [r.group, r.status]),
      [
        ["shipping", "regression"],
        ["billing", "unchanged"],
      ],
    );
    assert.equal(rows[0].n_items, 6);
  });
});
