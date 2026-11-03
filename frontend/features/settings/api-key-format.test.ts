import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ApiKey } from "@/lib/api/types";
import { keyAccess, scopeOption, sortApiKeys } from "./api-key-format";

function key(id: string, created_at: string, revoked_at: string | null = null): ApiKey {
  return {
    id,
    name: id,
    scope: "read",
    prefix: "og_",
    created_at,
    last_used_at: null,
    revoked_at,
  };
}

describe("api keys", () => {
  it("lists active keys first, newest first", () => {
    const sorted = sortApiKeys([
      key("old", "2026-01-01T00:00:00Z"),
      key("revoked", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"),
      key("new", "2026-02-01T00:00:00Z"),
    ]);
    assert.deepEqual(
      sorted.map((k) => k.id),
      ["new", "old", "revoked"],
    );
  });

  it("only admin sessions manage keys", () => {
    const base = { authenticated: true, key_name: null };
    assert.equal(keyAccess({ ...base, auth_required: false, scope: "admin" }), "auth-off");
    assert.equal(keyAccess({ ...base, auth_required: true, scope: "read" }), "not-admin");
    assert.equal(keyAccess({ ...base, auth_required: true, scope: "admin" }), "admin");
  });

  it("describes each scope", () => {
    assert.equal(scopeOption("ingest").label, "Ingest");
    assert.equal(scopeOption("admin").label, "Admin");
  });
});
