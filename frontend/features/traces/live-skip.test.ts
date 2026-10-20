import assert from "node:assert/strict";
import { test } from "node:test";
import type { Span } from "@/lib/api/types";
import { liveTraceSkipped } from "./live-skip";

function span(attributes: Record<string, unknown>): Span {
  return { attributes } as Span;
}

test("flags a live-marked trace without a live interaction", () => {
  assert.equal(
    liveTraceSkipped({ live_interaction_id: null, spans: [span({ "opengrade.live": true })] }),
    true,
  );
  assert.equal(
    liveTraceSkipped({ live_interaction_id: null, spans: [span({ "opengrade.live": "true" })] }),
    true,
  );
});

test("ignores bound, unmarked and experiment traces", () => {
  assert.equal(
    liveTraceSkipped({ live_interaction_id: "x", spans: [span({ "opengrade.live": true })] }),
    false,
  );
  assert.equal(liveTraceSkipped({ live_interaction_id: null, spans: [span({})] }), false);
  assert.equal(
    liveTraceSkipped({
      live_interaction_id: null,
      spans: [span({ "opengrade.live": true, "opengrade.experiment_id": "e" })],
    }),
    false,
  );
});
