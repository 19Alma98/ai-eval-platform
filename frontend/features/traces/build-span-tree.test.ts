import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildSpanTree, flattenVisible } from "./build-span-tree";

describe("buildSpanTree", () => {
  it("nests by parent_span_id", () => {
    const spans = [
      {
        span_id: "a",
        parent_span_id: null,
        name: "root",
        kind: "CHAIN",
        start_time: "2026-01-01T00:00:00Z",
        end_time: "2026-01-01T00:00:02Z",
        status: "ok",
        attributes: {},
        events: [],
      },
      {
        span_id: "b",
        parent_span_id: "a",
        name: "child",
        kind: "LLM",
        start_time: "2026-01-01T00:00:00.5Z",
        end_time: "2026-01-01T00:00:01.5Z",
        status: "ok",
        attributes: {},
        events: [],
      },
    ];
    const tree = buildSpanTree(spans);
    assert.equal(tree.length, 1);
    assert.equal(tree[0].span.span_id, "a");
    assert.equal(tree[0].children[0].span.span_id, "b");
    assert.equal(flattenVisible(tree, new Set()).length, 2);
  });
});
