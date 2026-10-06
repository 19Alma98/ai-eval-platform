import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  PROJECT_DEFAULT_SELECT,
  evaluatePackBody,
  metricsSetIdForCreate,
} from "./metrics-set-submit";

describe("metricsSetIdForCreate", () => {
  it("submits null for preselected project default", () => {
    assert.equal(metricsSetIdForCreate(PROJECT_DEFAULT_SELECT), null);
  });
  it("submits uuid when a concrete set is chosen", () => {
    assert.equal(metricsSetIdForCreate("abc"), "abc");
  });
});

describe("evaluatePackBody", () => {
  it("omits body fields when scoring bound/fallback set", () => {
    assert.deepEqual(
      evaluatePackBody({ overrideSetId: null, saveAsDefault: true }),
      {},
    );
  });
  it("sends override and save_as_default together", () => {
    assert.deepEqual(
      evaluatePackBody({ overrideSetId: "set-1", saveAsDefault: true }),
      { metrics_set_id: "set-1", save_as_default: true },
    );
  });
});
