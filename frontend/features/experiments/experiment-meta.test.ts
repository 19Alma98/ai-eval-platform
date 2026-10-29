import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Experiment } from "@/lib/api/types";
import {
  codeChange,
  experimentAppConfigChip,
  experimentAppConfigSnapshot,
  experimentCommit,
  experimentVersion,
  metricsSetBoundLabel,
  runMetricEntries,
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

describe("metricsSetBoundLabel", () => {
  it("returns project default when unbound", () => {
    assert.equal(
      metricsSetBoundLabel(experiment({ metrics_set_id: null }), []),
      "Project default",
    );
  });

  it("returns name and version when found", () => {
    assert.equal(
      metricsSetBoundLabel(
        experiment({ metrics_set_id: "set-1" }),
        [
          {
            id: "set-1",
            project_id: "proj",
            name: "rag",
            version: 2,
            description: null,
            is_project_default: false,
            created_at: "2026-10-07T00:00:00Z",
            updated_at: "2026-10-07T00:00:00Z",
            entry_count: 1,
            enabled_count: 1,
          },
        ],
      ),
      "rag v2",
    );
  });

  it("returns unknown label when set missing", () => {
    assert.equal(
      metricsSetBoundLabel(experiment({ metrics_set_id: "gone" }), []),
      "Unknown metrics set",
    );
  });
});

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

describe("runMetricEntries", () => {
  it("labels SDK run metrics and keeps custom ones", () => {
    assert.deepEqual(
      runMetricEntries({
        "opengrade.latency_p95_ms": 484.0394,
        "opengrade.error_rate": 0,
        "opengrade.latency_p50_ms": 25.0099,
        cost_usd: 0.123456,
      }),
      [
        ["Errors", "0%"],
        ["Latency p50", "25ms"],
        ["Latency p95", "484ms"],
        ["cost_usd", "0.1235"],
      ],
    );
  });
});

describe("experimentCommit / codeChange", () => {
  const sha = (c: string) => c.repeat(40);

  it("links GitHub commits and hides the SDK's default SHA version", () => {
    const exp = experiment({
      version: `${sha("a").slice(0, 12)}-dirty`,
      git: { commit: sha("a"), branch: "main", dirty: true, remote_url: "https://github.com/acme/app" },
    });
    assert.deepEqual(experimentCommit(exp), {
      sha: sha("a"),
      short: "aaaaaaa",
      branch: "main",
      dirty: true,
      href: `https://github.com/acme/app/commit/${sha("a")}`,
    });
    assert.equal(experimentVersion(exp), null);
    assert.equal(experimentVersion(experiment({ version: "1.4.0", git: exp.git })), "1.4.0");
  });

  it("has no commit link for unknown hosts", () => {
    const exp = experiment({ git: { commit: sha("a"), remote_url: "https://git.example.com/app" } });
    assert.equal(experimentCommit(exp)?.href, null);
    assert.equal(experimentCommit(experiment({})), null);
  });

  it("describes how code moved from baseline to candidate", () => {
    const remote = "https://gitlab.com/grp/app";
    assert.deepEqual(codeChange(null, { commit: sha("b") }), { kind: "unknown" });
    assert.deepEqual(codeChange({ commit: sha("a") }, { commit: sha("a"), dirty: true }), {
      kind: "same",
      dirty: true,
    });
    assert.deepEqual(
      codeChange({ commit: sha("a"), remote_url: remote }, { commit: sha("b"), remote_url: remote }),
      { kind: "changed", diffHref: `${remote}/-/compare/${sha("a")}...${sha("b")}` },
    );
    assert.deepEqual(codeChange({ commit: sha("a") }, { commit: sha("b") }), {
      kind: "changed",
      diffHref: null,
    });
  });
});
