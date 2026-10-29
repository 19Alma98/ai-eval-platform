import type { DatasetItem, GroupCompare } from "@/lib/api/types";
import { groupMetricsByEvaluator, type EvaluatorCompareRow } from "./group-metrics-by-evaluator";

/** Metadata keys that hold gold labels, not a way to slice questions. */
const GOLD_KEYS = new Set(["expected_doc_ids", "must_contain", "source_live_interaction_id"]);
const MAX_DISTINCT = 50;

/**
 * Metadata keys worth grouping by: present on some items, scalar (or list of scalars)
 * values, between 2 and 50 distinct values.
 */
export function groupableMetadataKeys(items: DatasetItem[]): string[] {
  const values = new Map<string, Set<string>>();
  for (const item of items) {
    for (const [key, value] of Object.entries(item.metadata ?? {})) {
      if (GOLD_KEYS.has(key) || !/^[A-Za-z0-9_-]+$/.test(key)) continue;
      const scalars = Array.isArray(value) ? value : [value];
      if (scalars.some((v) => v !== null && typeof v === "object")) continue;
      const seen = values.get(key) ?? new Set<string>();
      for (const v of scalars) seen.add(String(v));
      values.set(key, seen);
    }
  }
  return [...values.entries()]
    .filter(([, seen]) => seen.size >= 2 && seen.size <= MAX_DISTINCT)
    .map(([key]) => key)
    .sort();
}

export type GroupCompareRow = EvaluatorCompareRow & {
  group: string;
  n_items: number;
};

/** One row per (group, metric); groups with a regression first. */
export function groupCompareRows(groups: GroupCompare[]): GroupCompareRow[] {
  const rows = groups.flatMap((group) =>
    groupMetricsByEvaluator(group.metrics).map((row) => ({
      ...row,
      group: group.value,
      n_items: group.n_items,
    })),
  );
  const worse = new Set(rows.filter((r) => r.status === "regression").map((r) => r.group));
  return rows.sort((a, b) => {
    const rank = Number(worse.has(b.group)) - Number(worse.has(a.group));
    return rank || a.group.localeCompare(b.group);
  });
}
