export function sortMetricsForDisplay<T extends { status: string }>(metrics: T[]): T[] {
  const rank: Record<string, number> = {
    regression: 0,
    config_mismatch: 1,
    unavailable: 1,
    unchanged: 2,
    improved: 3,
  };
  return [...metrics].sort(
    (a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9),
  );
}
