import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { canWrite } from "./can-write";

describe("canWrite", () => {
  const base = { authenticated: true, key_name: null as string | null };

  it("allows writes when auth is off", () => {
    assert.equal(
      canWrite({ ...base, auth_required: false, scope: "admin" }, "open"),
      true,
    );
  });

  it("allows writes for admin sessions", () => {
    assert.equal(
      canWrite({ ...base, auth_required: true, scope: "admin" }, "open"),
      true,
    );
  });

  it("denies writes for read sessions", () => {
    assert.equal(
      canWrite({ ...base, auth_required: true, scope: "read" }, "open"),
      false,
    );
  });

  it("denies writes while checking or locked", () => {
    const status = { ...base, auth_required: true, scope: "admin" as const };
    assert.equal(canWrite(status, "checking"), false);
    assert.equal(canWrite(status, "locked"), false);
  });
});
