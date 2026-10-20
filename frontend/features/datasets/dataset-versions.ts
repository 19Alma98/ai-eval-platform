import type { Dataset } from "@/lib/api/types";

export type DatasetRow = Dataset & {
  /** Newest version of its test set (older versions are listed right under it). */
  latest: boolean;
  /** Number of versions sharing this name. */
  versionCount: number;
};

/**
 * One block per test set: newest version first, older versions under it.
 * Test sets are ordered by their newest version's creation time (newest first).
 */
export function groupDatasetVersions(datasets: Dataset[]): DatasetRow[] {
  const byName = new Map<string, Dataset[]>();
  for (const d of datasets) {
    const list = byName.get(d.name);
    if (list) list.push(d);
    else byName.set(d.name, [d]);
  }
  const groups = [...byName.values()].map((versions) =>
    [...versions].sort((a, b) => b.version - a.version),
  );
  groups.sort((a, b) => b[0].created_at.localeCompare(a[0].created_at));
  return groups.flatMap((versions) =>
    versions.map((d, i) => ({ ...d, latest: i === 0, versionCount: versions.length })),
  );
}
