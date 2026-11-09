import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { tracesWindowHref } from "./attribute-filters";

describe("tracesWindowHref", () => {
  it("builds a custom window deep link", () => {
    const href = tracesWindowHref({
      projectId: "p1",
      since: "2026-10-01T00:00:00.000Z",
      until: "2026-10-01T00:05:00.000Z",
      environment: "prod",
      version: "1.2.3",
      status: "error",
    });
    const params = new URLSearchParams(href.split("?")[1]);
    assert.equal(params.get("project"), "p1");
    assert.equal(params.get("range"), "custom");
    assert.equal(params.get("since"), "2026-10-01T00:00:00.000Z");
    assert.equal(params.get("until"), "2026-10-01T00:05:00.000Z");
    assert.equal(params.get("env"), "prod");
    assert.equal(params.get("version"), "1.2.3");
    assert.equal(params.get("status"), "error");
  });
});
