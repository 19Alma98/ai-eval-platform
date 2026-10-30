import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  parseCompareCols,
  parseDetailsOpen,
  serializeCompareCols,
} from "./compare-url-state";

describe("compare URL state", () => {
  it("defaults cols to ci+score when the param is absent", () => {
    assert.deepEqual([...parseCompareCols(null)].sort(), ["ci", "score"]);
  });

  it("parses a subset and serializes back, omitting the default", () => {
    const onlyCi = parseCompareCols("ci");
    assert.deepEqual([...onlyCi], ["ci"]);
    assert.equal(serializeCompareCols(onlyCi), "ci");
    assert.equal(serializeCompareCols(parseCompareCols(null)), null);
    assert.equal(serializeCompareCols(parseCompareCols("")), "");
  });

  it("opens details only for 1/true", () => {
    assert.equal(parseDetailsOpen(null), false);
    assert.equal(parseDetailsOpen("0"), false);
    assert.equal(parseDetailsOpen("1"), true);
    assert.equal(parseDetailsOpen("true"), true);
  });
});
