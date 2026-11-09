import assert from "node:assert/strict";
import { test } from "node:test";
import { EVALUATOR_PRESETS } from "./evaluator-presets";

test("safety LLM judges are offered as presets", () => {
  const kinds = EVALUATOR_PRESETS.filter((p) => p.type === "llm_judge").map((p) => p.config.kind);
  for (const kind of ["pii", "toxicity", "prompt_injection"]) {
    assert.ok(kinds.includes(kind as (typeof kinds)[number]), kind);
  }
});
