import assert from "node:assert/strict";
import { test } from "node:test";
import { productionScoreRows } from "./production-scores";

test("productionScoreRows puts feedback first and formats rates", () => {
  const rows = productionScoreRows({
    since: "2026-10-13T00:00:00Z",
    until: "2026-10-14T00:00:00Z",
    rows: [
      { name: "cites_source", source: "sdk", count: 10, mean: 0.7, pass_rate: 0.6 },
      { name: "user_feedback", source: "human", count: 4, mean: 0.75, pass_rate: 0.75 },
    ],
  });
  assert.deepEqual(rows, [
    { key: "user_feedback:human", label: "User feedback", count: 4, primary: "75% positive", secondary: null },
    { key: "cites_source:sdk", label: "cites_source", count: 10, primary: "0.70 mean", secondary: "60% pass" },
  ]);
  assert.deepEqual(productionScoreRows(undefined), []);
});

test("productionScoreRows labels non-human feedback with its source", () => {
  const rows = productionScoreRows({
    since: "2026-10-13T00:00:00Z",
    until: "2026-10-14T00:00:00Z",
    rows: [{ name: "user_feedback", source: "sdk", count: 2, mean: 0.5, pass_rate: null }],
  });
  assert.equal(rows[0].label, "User feedback (sdk)");
});
