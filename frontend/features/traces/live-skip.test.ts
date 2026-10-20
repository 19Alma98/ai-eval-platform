import assert from "node:assert/strict";
import { test } from "node:test";
import type { Span } from "@/lib/api/types";
import { liveSkipReason } from "./live-skip";

function span(attributes: Record<string, unknown>): Span {
  return { attributes } as Span;
}

test("live trace without captured content", () => {
  assert.equal(
    liveSkipReason({ live_interaction_id: null, spans: [span({ "opengrade.live": "true" })] }),
    "no_content",
  );
});

test("live trace with content but no live answer", () => {
  assert.equal(
    liveSkipReason({
      live_interaction_id: null,
      spans: [span({ "opengrade.live": true, "input.value": "", "output.value": "" })],
    }),
    "empty",
  );
});

test("ignores bound, unmarked and experiment traces", () => {
  assert.equal(
    liveSkipReason({ live_interaction_id: "x", spans: [span({ "opengrade.live": true })] }),
    null,
  );
  assert.equal(liveSkipReason({ live_interaction_id: null, spans: [span({})] }), null);
  assert.equal(
    liveSkipReason({
      live_interaction_id: null,
      spans: [span({ "opengrade.live": true, "opengrade.experiment_id": "e" })],
    }),
    null,
  );
});
