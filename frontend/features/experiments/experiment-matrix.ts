import type { Experiment, ExperimentSummary } from "@/lib/api/types";
import { experimentAppConfigChip, experimentModel, experimentVersion } from "./experiment-meta";

export type MetricCell = { mean: number | null; passRate: number | null; nScored: number };

export type MatrixRow = {
  experiment: Experiment;
  label: string;
  model: string | null;
  prompt: string | null;
  params: Record<string, string>;
  metrics: Record<string, MetricCell>;
};

export type MetricColumn = { key: string; label: string; kind: "evaluator" | "logged" };

const LOGGED_PREFIX = "logged:";
const SKIP_PARAM_KEYS = new Set(["content_hash"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Flatten scalar config values to dotted keys: {model: {temperature: 0}} → model.temperature. */
export function flattenParams(
  value: Record<string, unknown>,
  prefix = "",
  out: Record<string, string> = {},
): Record<string, string> {
  for (const [key, raw] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (SKIP_PARAM_KEYS.has(key)) continue;
    if (isRecord(raw)) {
      flattenParams(raw, path, out);
    } else if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") {
      const text = String(raw);
      // Long strings are prompt bodies, not comparable parameters.
      if (text.length <= 80) out[path] = text;
    }
  }
  return out;
}

/** Prompt identity: app-config name@version, or a prompt name / version param. */
export function experimentPrompt(experiment: Experiment): string | null {
  const chip = experimentAppConfigChip(experiment);
  const mc = experiment.model_config ?? {};
  const prompt = isRecord(mc.prompt) ? mc.prompt : null;
  const promptName =
    (prompt && typeof prompt.name === "string" && prompt.name.trim()) ||
    (typeof mc.prompt === "string" && mc.prompt.length <= 80 && mc.prompt.trim()) ||
    (typeof mc.prompt_name === "string" && mc.prompt_name.trim()) ||
    null;
  const promptVersion =
    (prompt && (prompt.version ?? null)) ?? mc.prompt_version ?? null;
  if (promptName) {
    return promptVersion != null ? `${promptName}@${String(promptVersion)}` : promptName;
  }
  if (chip) return chip.label;
  return promptVersion != null ? `v${String(promptVersion)}` : null;
}

export function buildMatrix(
  experiments: Experiment[],
  summaries: ExperimentSummary[],
): { rows: MatrixRow[]; columns: MetricColumn[] } {
  const byId = new Map(summaries.map((s) => [s.experiment_id, s]));
  const columns = new Map<string, MetricColumn>();
  const rows = experiments.map((experiment) => {
    const summary = byId.get(experiment.id);
    const metrics: Record<string, MetricCell> = {};
    for (const ev of summary?.evaluators ?? []) {
      const key = ev.evaluator_name?.trim() || ev.evaluator_id;
      metrics[key] = { mean: ev.mean_score, passRate: ev.pass_rate, nScored: ev.n_scored };
      if (!columns.has(key)) columns.set(key, { key, label: key, kind: "evaluator" });
    }
    for (const [name, value] of Object.entries(summary?.experiment_metrics ?? {})) {
      const key = `${LOGGED_PREFIX}${name}`;
      metrics[key] = { mean: value, passRate: null, nScored: 1 };
      if (!columns.has(key)) columns.set(key, { key, label: name, kind: "logged" });
    }
    return {
      experiment,
      label: experimentVersion(experiment) ?? experiment.name,
      model: experimentModel(experiment),
      prompt: experimentPrompt(experiment),
      params: flattenParams(experiment.model_config ?? {}),
      metrics,
    };
  });
  const ordered = [...columns.values()].sort((a, b) =>
    a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === "evaluator" ? -1 : 1,
  );
  return { rows, columns: ordered };
}

export type MatrixFilters = {
  model?: string | null;
  prompt?: string | null;
  datasetId?: string | null;
  param?: { key: string; value: string } | null;
};

export function filterRows(rows: MatrixRow[], filters: MatrixFilters): MatrixRow[] {
  return rows.filter(
    (row) =>
      (!filters.model || row.model === filters.model) &&
      (!filters.prompt || row.prompt === filters.prompt) &&
      (!filters.datasetId || row.experiment.dataset_id === filters.datasetId) &&
      (!filters.param || row.params[filters.param.key] === filters.param.value),
  );
}

export type SortState = { key: string; dir: "asc" | "desc" };

/** Sort by a metric column or "created"/"name"; rows without the value sink to the bottom. */
export function sortRows(rows: MatrixRow[], sort: SortState): MatrixRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  const value = (row: MatrixRow): number | string | null => {
    if (sort.key === "created") return new Date(row.experiment.created_at).getTime();
    if (sort.key === "name") return row.label.toLowerCase();
    return row.metrics[sort.key]?.mean ?? null;
  };
  return [...rows].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return va < vb ? -sign : va > vb ? sign : 0;
  });
}

/** Highest mean per column (higher is better for every built-in metric). */
export function bestByColumn(rows: MatrixRow[], columns: MetricColumn[]): Record<string, number> {
  const best: Record<string, number> = {};
  for (const col of columns) {
    if (col.kind !== "evaluator") continue;
    for (const row of rows) {
      const v = row.metrics[col.key]?.mean;
      if (v != null && (best[col.key] == null || v > best[col.key])) best[col.key] = v;
    }
  }
  return best;
}

/** Distinct values per param key that differ across rows (constant params are noise). */
export function varyingParams(rows: MatrixRow[]): Record<string, string[]> {
  const values: Record<string, Set<string>> = {};
  for (const row of rows) {
    for (const [key, value] of Object.entries(row.params)) {
      (values[key] ??= new Set()).add(value);
    }
  }
  const out: Record<string, string[]> = {};
  for (const [key, set] of Object.entries(values)) {
    const missing = rows.some((r) => !(key in r.params));
    if (set.size > 1 || (set.size === 1 && missing)) out[key] = [...set].sort();
  }
  return out;
}

/** Trend points in creation order (oldest first), one value per metric column. */
export function trendSeries(
  rows: MatrixRow[],
  columns: MetricColumn[],
): Array<Record<string, number | string | null>> {
  return [...rows]
    .sort(
      (a, b) =>
        new Date(a.experiment.created_at).getTime() - new Date(b.experiment.created_at).getTime(),
    )
    .map((row) => {
      const point: Record<string, number | string | null> = {
        label: row.label,
        id: row.experiment.id,
      };
      for (const col of columns) point[col.key] = row.metrics[col.key]?.mean ?? null;
      return point;
    });
}
