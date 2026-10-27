import type { Experiment, MetricsSetSummary } from "@/lib/api/types";
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

/** User-declared model label from experiment.model_config.model */
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
  return trimmed ? trimmed : null;
}

function snapshotAppConfigVersion(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** App config registry chip when bound via app_config_id or snapshot name+version. */
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

/** Frozen app-config snapshot fields from experiment.model_config when registry-bound. */
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

/** Run metrics logged by the SDK, with readable labels for the built-in ones. */
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
