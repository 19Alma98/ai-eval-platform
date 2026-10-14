import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Span, TraceDetail } from "@/lib/api/types";
import {
  buildRagView,
  claimsForChunk,
  highlightQuotes,
  questionFromInput,
} from "./rag-view";

function span(partial: Partial<Span> & Pick<Span, "span_id" | "kind">): Span {
  return {
    parent_span_id: null,
    name: partial.kind.toLowerCase(),
    start_time: "2026-01-01T00:00:00Z",
    end_time: "2026-01-01T00:00:01Z",
    status: "ok",
    attributes: {},
    events: [],
    ...partial,
  };
}

function trace(spans: Span[], extra: Partial<TraceDetail> = {}): TraceDetail {
  return {
    id: "t",
    project_id: "p",
    trace_id: "ab".repeat(16),
    name: "answer",
    status: "ok",
    start_time: "2026-01-01T00:00:00Z",
    end_time: "2026-01-01T00:00:02Z",
    input: null,
    output: null,
    metadata: {},
    environment: null,
    user_id: null,
    session_id: null,
    spans,
    ...extra,
  };
}

describe("buildRagView", () => {
  it("reads query, scored chunks, prompt and answer", () => {
    const view = buildRagView(
      trace(
        [
          span({
            span_id: "r",
            kind: "RETRIEVER",
            start_time: "2026-01-01T00:00:00.1Z",
            attributes: {
              "retrieval.documents": JSON.stringify([
                { id: "d1", title: "Policy", text: "Remote work is allowed.", score: 0.91 },
                { id: "d2", text: "Office hours", score: "0.4" },
              ]),
            },
          }),
          span({
            span_id: "k",
            kind: "RERANKER",
            start_time: "2026-01-01T00:00:00.2Z",
            attributes: {
              "reranker.output_documents.0.document.id": "d1",
              "reranker.output_documents.0.document.content": "Remote work is allowed.",
              "reranker.output_documents.0.document.score": 0.99,
            },
          }),
          span({
            span_id: "l",
            kind: "LLM",
            start_time: "2026-01-01T00:00:00.5Z",
            attributes: {
              "llm.input_messages.0.message.role": "system",
              "llm.input_messages.0.message.content": "Answer from context.",
              "llm.input_messages.1.message.role": "user",
              "llm.input_messages.1.message.content": "Can I work remotely?",
            },
          }),
        ],
        {
          input: JSON.stringify({ args: [], kwargs: { question: "Can I work remotely?" } }),
          output: "Yes.",
        },
      ),
    );
    assert.equal(view.query, "Can I work remotely?");
    assert.equal(view.answer, "Yes.");
    assert.deepEqual(
      view.stages.map((s) => [s.kind, s.chunks.map((c) => [c.id, c.score])]),
      [
        ["RETRIEVER", [["d1", 0.91], ["d2", 0.4]]],
        ["RERANKER", [["d1", 0.99]]],
      ],
    );
    assert.deepEqual(view.prompt.map((m) => m.role), ["system", "user"]);
    assert.equal(view.promptSpanId, "l");
  });

  it("falls back to the LLM output when the trace has none", () => {
    const view = buildRagView(
      trace([
        span({
          span_id: "l",
          kind: "LLM",
          attributes: { "gen_ai.prompt": "hi", "output.value": '{"answer": "hello"}' },
        }),
      ]),
    );
    assert.equal(view.answer, "hello");
    assert.deepEqual(view.prompt, [{ role: "user", content: "hi" }]);
    assert.deepEqual(view.stages, []);
  });
});

describe("questionFromInput", () => {
  it("picks the only string argument", () => {
    assert.equal(questionFromInput('{"args": ["<Bot object at 0x1>", "why?"]}'), "why?");
    assert.equal(questionFromInput("plain"), "plain");
  });
});

describe("judge claims on chunks", () => {
  const claims = [
    { text: "a", verdict: "supported", docIds: ["d1"], quote: "remote work", reasoning: null },
    { text: "b", verdict: "not_supported", docIds: [], quote: "is allowed", reasoning: null },
  ];

  it("highlights quoted ranges, overlapping included", () => {
    const parts = highlightQuotes("Remote work is allowed.", claims);
    assert.deepEqual(
      parts.map((p) => [p.text, p.claimIndexes]),
      [
        ["Remote work", [0]],
        [" ", []],
        ["is allowed", [1]],
        [".", []],
      ],
    );
  });

  it("links claims by doc id or quote", () => {
    const chunk = { id: "d2", title: null, text: "It is allowed here", score: null };
    assert.deepEqual(claimsForChunk(chunk, claims), [1]);
    assert.deepEqual(claimsForChunk({ ...chunk, id: "d1" }, claims), [0, 1]);
  });
});
