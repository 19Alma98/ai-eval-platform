import type { Experiment, GitInfo, MetricsSetSummary } from "@/lib/api/types";
import { formatDurationMs, formatPercent } from "@/lib/format";

export function metricsSetBoundLabel(
  experiment: Pick<Experiment, "metrics_set_id">,
  sets: MetricsSetSummary[] | undefined,
  resolved?: Pick<MetricsSetSummary, "name" | "version"> | null,
): string {
  const id = experiment.metrics_set_id;
  if (!id) return "Project default";
  const found = sets?.find((s) => s.id === id) ?? resolved;
  if (found) return `${found.name} v${found.version}`;
  return "Unknown metrics set";
}

export function experimentModel(experiment: Experiment): string | null {
  const nested = experiment.model_config?.model;
  if (
    nested &&
    typeof nested === "object" &&
    nested !== null &&
    "model_id" in nested
  ) {
    const id = (nested as { model_id?: unknown }).model_id;
    if (typeof id === "string" && id.trim()) return id.trim();
  }
  const raw = experiment.model_config?.model;
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function experimentVersion(experiment: Experiment): string | null {
  const trimmed = experiment.version?.trim();
  if (!trimmed) return null;
  // The SDK defaults the version to the short SHA, already shown as the commit.
  const prefix = trimmed.replace(/-dirty$/, "");
  if (prefix.length >= 7 && experiment.git?.commit?.startsWith(prefix)) return null;
  return trimmed;
}

export type ExperimentCommit = {
  sha: string;
  short: string;
  branch: string | null;
  dirty: boolean;
  href: string | null;
};

function remoteRoute(remote: string | null | undefined, route: string): string | null {
  if (!remote || !/^https?:\/\//.test(remote)) return null;
  const base = remote.replace(/\/+$/, "");
  if (base.includes("github")) return `${base}/${route}`;
  if (base.includes("gitlab")) return `${base}/-/${route}`;
  return null;
}

export function experimentCommit(
  experiment: Pick<Experiment, "git">,
): ExperimentCommit | null {
  const git = experiment.git;
  const sha = git?.commit?.trim();
  if (!git || !sha) return null;
  return {
    sha,
    short: sha.slice(0, 7),
    branch: git.branch?.trim() || null,
    dirty: git.dirty === true,
    href: remoteRoute(git.remote_url, `commit/${sha}`),
  };
}

export type CodeChange =
  | { kind: "unknown" }
  | { kind: "same"; dirty: boolean }
  | { kind: "changed"; diffHref: string | null };

/** How the code moved from baseline to candidate, as far as the recorded commits tell. */
export function codeChange(
  baseline: GitInfo | null | undefined,
  candidate: GitInfo | null | undefined,
): CodeChange {
  if (!baseline?.commit || !candidate?.commit) return { kind: "unknown" };
  if (baseline.commit === candidate.commit) {
    return { kind: "same", dirty: Boolean(baseline.dirty || candidate.dirty) };
  }
  const sameRemote = baseline.remote_url && baseline.remote_url === candidate.remote_url;
  return {
    kind: "changed",
    diffHref: sameRemote
      ? remoteRoute(candidate.remote_url, `compare/${baseline.commit}...${candidate.commit}`)
      : null,
  };
}

function snapshotAppConfigVersion(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function experimentAppConfigChip(
  experiment: Experiment,
): { familyName: string; label: string } | null {
  const mc = experiment.model_config ?? {};
  const familyName =
    typeof mc.name === "string" ? mc.name.trim() : "";
  const configVersion = snapshotAppConfigVersion(mc.version);
  const hasBinding =
    Boolean(experiment.app_config_id) ||
    (familyName.length > 0 && configVersion !== null);
  if (!hasBinding || !familyName || configVersion === null) return null;
  return {
    familyName,
    label: `${familyName}@${configVersion}`,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export function experimentAppConfigSnapshot(experiment: Experiment): {
  prompt: Record<string, unknown>;
  model: Record<string, unknown>;
  retrieval: Record<string, unknown>;
  contentHash: string | null;
} | null {
  if (!experimentAppConfigChip(experiment)) return null;
  const mc = experiment.model_config ?? {};
  const hashRaw = mc.content_hash;
  return {
    prompt: asRecord(mc.prompt) ?? {},
    model: asRecord(mc.model) ?? {},
    retrieval: asRecord(mc.retrieval) ?? {},
    contentHash:
      typeof hashRaw === "string" && hashRaw.trim() ? hashRaw.trim() : null,
  };
}

const RUN_METRIC_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  "opengrade.error_rate": { label: "Errors", format: (v) => formatPercent(v) },
  "opengrade.latency_p50_ms": { label: "Latency p50", format: formatDurationMs },
  "opengrade.latency_p95_ms": { label: "Latency p95", format: formatDurationMs },
};

export function runMetricEntries(metrics: Record<string, number>): [string, string][] {
  const builtIn: [string, string][] = [];
  const custom: [string, string][] = [];
  for (const [key, value] of Object.entries(metrics)) {
    const known = RUN_METRIC_LABELS[key];
    if (known) builtIn.push([known.label, known.format(value)]);
    else custom.push([key, value.toLocaleString("en-US", { maximumFractionDigits: 4 })]);
  }
  builtIn.sort(([a], [b]) => a.localeCompare(b));
  custom.sort(([a], [b]) => a.localeCompare(b));
  return [...builtIn, ...custom];
}
