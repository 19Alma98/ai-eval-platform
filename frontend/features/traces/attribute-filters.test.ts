import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  EMPTY_ATTRIBUTE_FILTERS,
  addChip,
  chipsOf,
  metadataEntries,
  parseFilterInput,
  parseMetadataPair,
  readAttributeFilters,
  removeChip,
  tracesFilteredHref,
  writeAttributeFilters,
} from "./attribute-filters";

describe("parseFilterInput", () => {
  it("reads prefixes, metadata pairs and bare tags", () => {
    assert.deepEqual(parseFilterInput("tag:beta"), { kind: "tag", value: "beta" });
    assert.deepEqual(parseFilterInput(" User: u1 "), { kind: "user", value: "u1" });
    assert.deepEqual(parseFilterInput("session:chat:1"), { kind: "session", value: "chat:1" });
    assert.deepEqual(parseFilterInput("tenant:acme"), { kind: "meta", value: "tenant:acme" });
    assert.deepEqual(parseFilterInput("beta"), { kind: "tag", value: "beta" });
  });

  it("rejects empty or half pairs", () => {
    assert.equal(parseFilterInput("  "), null);
    assert.equal(parseFilterInput("tenant:"), null);
    assert.equal(parseFilterInput(":acme"), null);
    assert.equal(parseMetadataPair("no-colon"), null);
  });
});

describe("URL round trip", () => {
  it("reads, dedupes and writes back, keeping other params", () => {
    const params = new URLSearchParams(
      "range=all&tag=beta&tag=beta&tag=eu&meta=tenant:acme&meta=bad&user=u1",
    );
    const filters = readAttributeFilters(params);
    assert.deepEqual(filters, {
      tags: ["beta", "eu"],
      metadata: ["tenant:acme"],
      user: "u1",
      session: null,
    });
    const written = writeAttributeFilters(params, removeChip(filters, { kind: "tag", value: "beta" }));
    assert.equal(written.toString(), "range=all&tag=eu&meta=tenant%3Aacme&user=u1");
  });

  it("lists chips and builds a filtered link", () => {
    const f = addChip(addChip(EMPTY_ATTRIBUTE_FILTERS, { kind: "session", value: "s1" }), {
      kind: "tag",
      value: "eu",
    });
    assert.deepEqual(
      chipsOf(f).map((c) => c.kind),
      ["session", "tag"],
    );
    assert.equal(tracesFilteredHref({ kind: "user", value: "u 1" }), "/traces?range=all&user=u+1");
  });
});

describe("metadataEntries", () => {
  it("keeps scalar, non-internal entries", () => {
    assert.deepEqual(
      metadataEntries({ tenant: "acme", n: 3, beta: true, _span_count: 4, cfg: { k: 1 }, e: "" }),
      [
        ["tenant", "acme"],
        ["n", "3"],
        ["beta", "true"],
      ],
    );
  });
});
