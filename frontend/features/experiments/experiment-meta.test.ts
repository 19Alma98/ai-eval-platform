import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Experiment } from "@/lib/api/types";
import {
  experimentAppConfigChip,
  experimentAppConfigSnapshot,
} from "./experiment-meta";

function experiment(
  overrides: Partial<Experiment> & { model_config?: Record<string, unknown> },
): Experiment {
  return {
    id: "exp",
    project_id: "proj",
    name: "run",
    dataset_id: "ds",
    model_config: {},
    version: null,
    baseline_experiment_id: null,
    status: "created",
    created_at: "2026-10-07T00:00:00Z",
    app_config_id: null,
    metrics_set_id: null,
    ...overrides,
  };
}

describe("experimentAppConfigChip", () => {
  it("returns family@version from snapshot", () => {
    const chip = experimentAppConfigChip(
      experiment({
        app_config_id: "cfg-1",
        model_config: { name: "rag-hr", version: 2 },
      }),
    );
    assert.deepEqual(chip, { familyName: "rag-hr", label: "rag-hr@2" });
  });
});

describe("experimentAppConfigSnapshot", () => {
  it("returns null without registry binding", () => {
    assert.equal(
      experimentAppConfigSnapshot(
        experiment({ model_config: { model: "gpt-4o" } }),
      ),
      null,
    );
  });

  it("exposes prompt model retrieval and hash", () => {
    const snap = experimentAppConfigSnapshot(
      experiment({
        app_config_id: "cfg-1",
        model_config: {
          name: "rag-hr",
          version: 3,
          content_hash: "abcdef0123456789",
          prompt: { system: "Be concise." },
          model: { model_id: "gpt-demo" },
          retrieval: { top_k: 5 },
        },
      }),
    );
    assert.ok(snap);
    assert.deepEqual(snap.prompt, { system: "Be concise." });
    assert.deepEqual(snap.model, { model_id: "gpt-demo" });
    assert.deepEqual(snap.retrieval, { top_k: 5 });
    assert.equal(snap.contentHash, "abcdef0123456789");
  });
});
