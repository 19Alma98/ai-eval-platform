import type { VersionSummary } from "@/lib/api/types";

export type VersionMetricColumn = { key: string; name: string; source: string };

/** Score metrics shown per version: the `limit` with the most samples across versions. */
export function versionMetricColumns(rows: VersionSummary[], limit = 3): VersionMetricColumn[] {
  const totals = new Map<string, VersionMetricColumn & { n: number }>();
  for (const row of rows) {
    for (const m of row.metrics) {
      const key = `${m.source}:${m.name}`;
      const current = totals.get(key) ?? { key, name: m.name, source: m.source, n: 0 };
      current.n += m.n;
      totals.set(key, current);
    }
  }
  return [...totals.values()]
    .sort((a, b) => b.n - a.n || a.key.localeCompare(b.key))
    .slice(0, limit)
    .map(({ key, name, source }) => ({ key, name, source }));
}

export function versionFailRate(row: VersionSummary, column: VersionMetricColumn): number | null {
  const metric = row.metrics.find((m) => m.name === column.name && m.source === column.source);
  return metric?.fail_rate ?? null;
}

/** Index of the version doing worst on a column (highest value), for highlighting. */
export function worstIndex(values: (number | null)[]): number | null {
  let worst: number | null = null;
  values.forEach((v, i) => {
    if (v == null) return;
    if (worst == null || v > (values[worst] ?? -Infinity)) worst = i;
  });
  const defined = values.filter((v) => v != null);
  return defined.length > 1 && new Set(defined).size > 1 ? worst : null;
}
