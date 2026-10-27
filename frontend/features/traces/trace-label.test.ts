import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { traceLabel } from "./trace-label";

describe("traceLabel", () => {
  it("leads with the question and names the experiment", () => {
    assert.deepEqual(
      traceLabel({ name: "opengrade.eval candidate-1", input_preview: "Where is HR?" }),
      { title: "Where is HR?", subtitle: "Experiment · candidate-1" },
    );
  });

  it("falls back to the span name without input", () => {
    assert.deepEqual(traceLabel({ name: "people-ops-rag", input_preview: null }), {
      title: "people-ops-rag",
      subtitle: null,
    });
  });
});
