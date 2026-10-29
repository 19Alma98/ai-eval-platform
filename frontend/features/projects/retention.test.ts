import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { describePending } from "./retention";

describe("describePending", () => {
  it("lists non-zero counts with plurals", () => {
    const base = {
      retention_days: 30,
      cutoff: null,
      dry_run: true,
      traces: 12,
      traces_kept: 0,
      live_interactions: 1,
      trace_scores: 0,
      alert_events: 0,
    };
    assert.equal(describePending(base), "12 traces, 1 live answer");
    assert.equal(describePending({ ...base, traces: 0, live_interactions: 0 }), "nothing");
  });
});
