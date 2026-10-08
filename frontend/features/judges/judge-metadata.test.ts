import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  liveJudgeWarningMessage,
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

describe("liveJudgeWarningMessage", () => {
  it("returns null when there are no warnings", () => {
    assert.equal(liveJudgeWarningMessage(undefined), null);
    assert.equal(liveJudgeWarningMessage([]), null);
  });

  it("joins warning_detail messages from the list response", () => {
    assert.equal(
      liveJudgeWarningMessage([
        { warning_detail: { message: "groundedness: use rubric." } },
        { warning_detail: { message: "answer_relevance: use rubric." } },
      ]),
      "groundedness: use rubric. answer_relevance: use rubric.",
    );
  });

  it("falls back when messages are missing", () => {
    assert.equal(liveJudgeWarningMessage([{ warning_detail: {} }]), "Judge model unsuitable");
  });
});
