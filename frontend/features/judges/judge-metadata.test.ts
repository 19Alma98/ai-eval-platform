import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { LiveInteraction } from "@/lib/api/types";
import {
  liveUnsuitableRate,
  parseJudgeClaims,
  runJudgeWarning,
  verdictTone,
} from "./judge-metadata";

describe("parseJudgeClaims", () => {
  it("returns null without claims", () => {
    assert.equal(parseJudgeClaims({}), null);
    assert.equal(parseJudgeClaims(undefined), null);
  });

  it("parses claims and drops malformed entries", () => {
    const claims = parseJudgeClaims({
      claims: [
        { text: "26 days", verdict: "supported", doc_ids: ["kb-1"], quote: "26", reasoning: "r" },
        { verdict: "missing" },
        "junk",
      ],
    });
    assert.deepEqual(claims, [
      { text: "26 days", verdict: "supported", docIds: ["kb-1"], quote: "26", reasoning: "r" },
    ]);
  });
});

describe("verdictTone", () => {
  it("maps verdicts to status tones", () => {
    assert.equal(verdictTone("supported"), "ok");
    assert.equal(verdictTone("covered"), "ok");
    assert.equal(verdictTone("contradicted"), "fail");
    assert.equal(verdictTone("not_supported"), "warn");
    assert.equal(verdictTone("missing"), "warn");
  });
});

describe("runJudgeWarning", () => {
  it("returns the warning message when flagged", () => {
    assert.equal(
      runJudgeWarning({
        warnings: ["judge_model_unsuitable"],
        warning_detail: { message: "use rubric" },
      }),
      "use rubric",
    );
    assert.equal(runJudgeWarning({}), null);
  });
});

function row(errorTypes: (string | null)[]): LiveInteraction {
  return {
    scores: errorTypes.map((t, i) => ({
      id: String(i),
      live_interaction_id: "x",
      evaluator_id: null,
      kind: "groundedness",
      score: null,
      label: t ? "ERROR" : "PASS",
      explanation: null,
      threshold: null,
      created_at: "",
      metadata: t ? { error_type: t } : {},
    })),
  } as unknown as LiveInteraction;
}

describe("liveUnsuitableRate", () => {
  it("is the share of judge scores with invalid output", () => {
    const rows = [row(["judge_output_invalid", null]), row([null, "llm_unavailable"])];
    assert.equal(liveUnsuitableRate(rows), 0.25);
    assert.equal(liveUnsuitableRate([]), 0);
  });
});
