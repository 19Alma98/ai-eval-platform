import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Span } from "@/lib/api/types";
import { buildSpanView, decodeValue, groupAttributes } from "./span-view";

function span(partial: Partial<Span> & Pick<Span, "kind">): Span {
  return {
    span_id: "s1",
    parent_span_id: "root",
    name: partial.kind.toLowerCase(),
    start_time: "2026-01-01T00:00:00Z",
    end_time: "2026-01-01T00:00:01.250Z",
    status: "ok",
    attributes: {},
    events: [],
    ...partial,
  };
}

describe("buildSpanView", () => {
  it("reads an OpenInference LLM span into model, usage and messages", () => {
    const view = buildSpanView(
      span({
        kind: "LLM",
        attributes: {
          "llm.model_name": "gpt-4o-mini",
          "llm.provider": "openai",
          "llm.invocation_parameters": '{"temperature":0.2,"max_tokens":256,"stream":false}',
          "llm.input_messages.0.message.role": "system",
          "llm.input_messages.0.message.content": "Answer from context.",
          "llm.input_messages.1.message.role": "user",
          "llm.input_messages.1.message.content": "What is our VPN?",
          "llm.output_messages.0.message.role": "assistant",
          "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "search",
          "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments": '{"q":"vpn"}',
          "llm.token_count.prompt": 120,
          "llm.token_count.completion": 30,
          "input.value": '{"model":"gpt-4o-mini","messages":[]}',
        },
      }),
    );
    assert.equal(view.model, "gpt-4o-mini");
    assert.equal(view.provider, "openai");
    assert.equal(view.durationMs, 1250);
    assert.deepEqual(view.usage, { prompt: 120, completion: 30, total: 150, cost: null });
    assert.deepEqual(view.parameters, [
      ["temperature", "0.2"],
      ["max_tokens", "256"],
      ["stream", "false"],
    ]);
    assert.deepEqual(
      view.inputMessages.map((m) => [m.role, m.content]),
      [
        ["system", "Answer from context."],
        ["user", "What is our VPN?"],
      ],
    );
    assert.equal(view.outputMessages.length, 1);
    assert.equal(view.outputMessages[0].content, null);
    assert.deepEqual(view.outputMessages[0].toolCalls, [{ name: "search", arguments: '{"q":"vpn"}' }]);
  });

  it("falls back to the chat completion body for the response", () => {
    const view = buildSpanView(
      span({
        kind: "LLM",
        attributes: {
          "llm.input_messages.0.message.content": "hi",
          "output.value": JSON.stringify({
            choices: [{ message: { role: "assistant", content: "Hello!" } }],
          }),
        },
      }),
    );
    assert.deepEqual(
      view.outputMessages.map((m) => [m.role, m.content]),
      [["assistant", "Hello!"]],
    );
  });

  it("surfaces exception events as the span error", () => {
    const view = buildSpanView(
      span({
        kind: "TOOL",
        status: "error",
        events: [
          {
            name: "exception",
            time_unix_nano: "1767225600500000000",
            attributes: { "exception.type": "TimeoutError", "exception.message": "took too long" },
          },
        ],
      }),
    );
    assert.equal(view.error?.type, "TimeoutError");
    assert.equal(view.error?.message, "took too long");
    assert.equal(view.events[0].offsetMs, 500);
  });
});

describe("decodeValue", () => {
  it("unwraps the SDK's args/kwargs envelope", () => {
    assert.equal(decodeValue('{"args":[],"kwargs":{"question":"hi"}}'), "hi");
    assert.equal(decodeValue('{"args":["<Foo object at 0x1>","hi"],"kwargs":{}}'), "hi");
    assert.deepEqual(decodeValue('{"args":[],"kwargs":{"a":1,"b":2}}'), { a: 1, b: 2 });
  });

  it("leaves plain text alone", () => {
    assert.equal(decodeValue("hello"), "hello");
    assert.equal(decodeValue("{not json"), "{not json");
  });
});

describe("groupAttributes", () => {
  it("separates model, messages and plumbing", () => {
    const groups = groupAttributes({
      "llm.model_name": "m",
      "llm.input_messages.0.message.content": "x",
      "input.value": "{}",
      "service.name": "app",
      "telemetry.sdk.name": "opentelemetry",
      "opengrade.live": true,
      "rerank.top_k": 5,
    });
    assert.deepEqual(
      groups.map((g) => [g.id, g.entries.map(([k]) => k)]),
      [
        ["model", ["llm.model_name"]],
        ["custom", ["rerank.top_k"]],
        ["context", ["opengrade.live"]],
        ["io", ["input.value"]],
        ["messages", ["llm.input_messages.0.message.content"]],
        ["resource", ["service.name", "telemetry.sdk.name"]],
      ],
    );
  });
});
