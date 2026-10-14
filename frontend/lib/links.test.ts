import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  experimentItemHref,
  experimentsCompareHref,
  liveRunHref,
  traceHref,
} from "./links";

describe("deep links", () => {
  it("keep the project in the query string", () => {
    assert.equal(traceHref("p1", "ab12"), "/traces/ab12?project=p1");
    assert.equal(liveRunHref(null, "x"), "/live-runs/x");
  });

  it("address a single experiment item", () => {
    assert.equal(
      experimentItemHref("p1", "e1", "i/1"),
      "/experiments/e1?item=i%2F1&project=p1",
    );
  });

  it("list the experiments to compare", () => {
    assert.equal(
      experimentsCompareHref("p1", ["a", "b"]),
      "/experiments/compare?ids=a%2Cb&project=p1",
    );
  });
});
