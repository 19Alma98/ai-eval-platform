import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Span } from "@/lib/api/types";
import { spanInputOutput, spanTokenSummary } from "./span-metrics";

function span(kind: string, attributes: Record<string, unknown>): Span {
  return {
    span_id: "a",
    parent_span_id: "root",
    name: kind.toLowerCase(),
    kind,
    start_time: "2026-01-01T00:00:00Z",
    end_time: "2026-01-01T00:00:01Z",
    status: "ok",
    attributes,
    events: [],
  };
}

describe("spanInputOutput", () => {
  it("reads OpenInference input.value / output.value on tool spans", () => {
    const io = spanInputOutput(
      span("TOOL", {
        "tool.name": "get_weather",
        "input.value": '{"city":"Rome"}',
        "output.value": "sunny",
      }),
    );
    assert.equal(io.input, '{"city":"Rome"}');
    assert.equal(io.output, "sunny");
  });

  it("reads GenAI messages on LLM spans", () => {
    const io = spanInputOutput(
      span("LLM", { "gen_ai.prompt": "hi", "gen_ai.completion": "hello" }),
    );
    assert.equal(io.input, "hi");
    assert.equal(io.output, "hello");
  });

  it("is undefined when content was redacted at ingestion", () => {
    const io = spanInputOutput(span("RETRIEVER", { "retrieval.documents": "[]" }));
    assert.equal(io.input, undefined);
    assert.equal(io.output, undefined);
  });
});

describe("spanTokenSummary", () => {
  it("reads OpenInference token counts", () => {
    const t = spanTokenSummary(
      span("LLM", {
        "llm.token_count.total": 30,
        "llm.token_count.prompt": "20",
        "llm.token_count.completion": 10,
      }),
    );
    assert.deepEqual(t, { total: "30", prompt: "20", completion: "10" });
  });
});
