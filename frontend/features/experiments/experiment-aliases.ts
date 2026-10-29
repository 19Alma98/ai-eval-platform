import type { ExperimentAlias } from "@/lib/api/types";

/** Convention used by CLI `--promote main` and `baseline: alias:main`. */
export const MAIN_ALIAS = "main";

export const PRESET_EXPERIMENT_ALIASES = [
  "main",
  "production",
  "candidate",
] as const;

/** Statuses the server rejects when setting an alias (see SetExperimentAlias). */
export const UNPROMOTABLE_STATUSES = new Set([
  "running",
  "failed",
  "cancelled",
]);

export function isExperimentPromotable(status: string): boolean {
  return !UNPROMOTABLE_STATUSES.has(status);
}

/** Map experiment id → alias names that currently point at it (sorted). */
export function aliasesByExperimentId(
  aliases: readonly ExperimentAlias[],
): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const alias of aliases) {
    const list = map.get(alias.experiment_id) ?? [];
    list.push(alias.name);
    map.set(alias.experiment_id, list);
  }
  for (const [, names] of map) {
    names.sort((a, b) => {
      if (a === MAIN_ALIAS) return -1;
      if (b === MAIN_ALIAS) return 1;
      return a.localeCompare(b);
    });
  }
  return map;
}

export function aliasTargetId(
  aliases: readonly ExperimentAlias[],
  name: string,
): string | null {
  const needle = name.trim();
  if (!needle) return null;
  const row = aliases.find((a) => a.name === needle);
  return row?.experiment_id ?? null;
}

/** True when the API 400 detail is an exam (dataset / metrics set) mismatch. */
export function isExamMismatchError(message: string): boolean {
  const lower = message.toLowerCase();
  return (
    lower.includes("force=true") ||
    (lower.includes("different") &&
      (lower.includes("dataset") || lower.includes("metrics set")))
  );
}

/**
 * Prefer `main` as compare baseline when no explicit baseline is set, but only
 * when it shares the candidate's dataset (avoid silent exam mismatch).
 */
export function defaultBaselineFromMainAlias(opts: {
  baselineFromQuery: string | null | undefined;
  baselineExperimentId: string | null | undefined;
  mainTargetId: string | null;
  candidateDatasetId: string | null | undefined;
  mainDatasetId: string | null | undefined;
}): string | null {
  if (opts.baselineFromQuery?.trim()) return opts.baselineFromQuery.trim();
  if (opts.baselineExperimentId) return opts.baselineExperimentId;
  if (!opts.mainTargetId) return null;
  if (
    opts.candidateDatasetId &&
    opts.mainDatasetId &&
    opts.candidateDatasetId !== opts.mainDatasetId
  ) {
    return null;
  }
  return opts.mainTargetId;
}
