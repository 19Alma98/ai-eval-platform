import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Evaluator } from "@/lib/api/types";
import {
  EMPTY_JUDGE_DRAFT,
  buildJudgeConfig,
  judgeDraftError,
  judgesNotInSet,
  latestCustomJudges,
  nextJudgeVersion,
  parseThreshold,
} from "./custom-judge";

function evaluator(name: string, version: number, kind = "custom_judge"): Evaluator {
  return { id: `${name}-${version}`, project_id: "p", name, type: "llm_judge", config: { kind }, version };
}

describe("buildJudgeConfig", () => {
  it("always includes the answer and keeps a canonical field order", () => {
    const config = buildJudgeConfig({
      ...EMPTY_JUDGE_DRAFT,
      criteria: "  Polite.  ",
      fields: ["documents", "input"],
    });
    assert.deepEqual(config, {
      kind: "custom_judge",
      criteria: "Polite.",
      scale: "1-5",
      fields: ["input", "output", "documents"],
    });
  });
  it("adds live, threshold and model only when set", () => {
    const config = buildJudgeConfig({
      ...EMPTY_JUDGE_DRAFT,
      criteria: "c",
      scale: "binary",
      live: true,
      threshold: "0.8",
      model: " gpt-x ",
    });
    assert.equal(config.live, true);
    assert.equal(config.threshold, 0.8);
    assert.equal(config.model, "gpt-x");
  });
});

describe("judgeDraftError", () => {
  it("validates name, criteria, live + reference and threshold", () => {
    const ok = { ...EMPTY_JUDGE_DRAFT, criteria: "c" };
    assert.equal(judgeDraftError("tone", ok), null);
    assert.match(judgeDraftError(" ", ok) ?? "", /name/);
    assert.match(judgeDraftError("tone", EMPTY_JUDGE_DRAFT) ?? "", /check/);
    assert.match(
      judgeDraftError("tone", { ...ok, live: true, fields: ["expected"] }) ?? "",
      /live judge/,
    );
    assert.match(judgeDraftError("tone", { ...ok, threshold: "2" }) ?? "", /between 0 and 1/);
  });
  it("parses thresholds", () => {
    assert.equal(parseThreshold("0.25"), 0.25);
    assert.equal(typeof parseThreshold(""), "string");
    assert.equal(typeof parseThreshold("abc"), "string");
  });
});

describe("latestCustomJudges / nextJudgeVersion", () => {
  const all = [
    evaluator("tone", 1),
    evaluator("tone", 3),
    evaluator("brevity", 1),
    evaluator("groundedness", 1, "groundedness"),
  ];
  it("keeps the latest version of custom judges only", () => {
    assert.deepEqual(
      latestCustomJudges(all).map((e) => `${e.name}@${e.version}`),
      ["brevity@1", "tone@3"],
    );
  });
  it("bumps the version per name", () => {
    assert.equal(nextJudgeVersion(all, "tone"), 4);
    assert.equal(nextJudgeVersion(all, "new"), 1);
  });
});

describe("judgesNotInSet", () => {
  it("hides judges already in the set by name or evaluator id", () => {
    const all = [evaluator("tone", 1), evaluator("brevity", 1), evaluator("policy", 2)];
    const entries = [
      { kind: "tone", evaluator_id: "x" },
      { kind: "renamed", evaluator_id: "policy-2" },
    ];
    assert.deepEqual(
      judgesNotInSet(all, entries).map((e) => e.name),
      ["brevity"],
    );
  });
});
