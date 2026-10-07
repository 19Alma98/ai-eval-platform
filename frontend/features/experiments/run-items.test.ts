import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DatasetItem, ExperimentItemOutput } from "@/lib/api/types";
import {
  buildRunItemViews,
  shouldRenderRunItemsSection,
} from "./run-items";

function item(id: string, question: string): DatasetItem {
  return {
    id,
    dataset_id: "ds",
    input: question,
    expected_output: "gold",
    actual_output: null,
    context: null,
    metadata: {},
    source_trace_id: null,
    source_span_id: null,
  };
}

describe("shouldRenderRunItemsSection", () => {
  it("is shown before any evaluation run exists", () => {
    assert.equal(shouldRenderRunItemsSection({ hasEvaluationRun: false }), true);
  });
});

describe("buildRunItemViews", () => {
  it("keeps questions and bound answers when results are empty", () => {
    const items = [item("item-1", "How many PTO days?")];
    const outputs: ExperimentItemOutput[] = [
      {
        id: "out-1",
        experiment_id: "exp",
        dataset_item_id: "item-1",
        actual_output: "20 days",
        context: null,
        metadata: { source_trace_id: "abc" },
        updated_at: "2026-10-06T00:00:00Z",
      },
    ];
    const views = buildRunItemViews(items, outputs, []);
    assert.equal(views.length, 1);
    assert.equal(views[0].question, "How many PTO days?");
    assert.equal(views[0].actualOutput, "20 days");
    assert.equal(views[0].score, null);
  });

  it("does not treat latency/tokens as retrieved documents", () => {
    const items = [item("item-1", "q")];
    const outputs: ExperimentItemOutput[] = [
      {
        id: "out-1",
        experiment_id: "exp",
        dataset_item_id: "item-1",
        actual_output: "a",
        context: {
          latency_ms: 100,
          total_tokens: 10,
          prompt_tokens: 4,
          completion_tokens: 6,
        },
        metadata: {},
        updated_at: "2026-10-06T00:00:00Z",
      },
    ];
    const views = buildRunItemViews(items, outputs, []);
    assert.equal(views[0].retrievedDocuments, null);
    assert.deepEqual(views[0].context, {
      latency_ms: 100,
      total_tokens: 10,
      prompt_tokens: 4,
      completion_tokens: 6,
    });
  });

  it("exposes empty documents list as empty retrieval", () => {
    const items = [item("item-1", "q")];
    const outputs: ExperimentItemOutput[] = [
      {
        id: "out-1",
        experiment_id: "exp",
        dataset_item_id: "item-1",
        actual_output: "a",
        context: { documents: [], latency_ms: 50 },
        metadata: {},
        updated_at: "2026-10-06T00:00:00Z",
      },
    ];
    const views = buildRunItemViews(items, outputs, []);
    assert.deepEqual(views[0].retrievedDocuments, []);
  });
});
