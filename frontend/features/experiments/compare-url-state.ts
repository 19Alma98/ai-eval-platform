export type CompareOptionalColumn = "ci" | "score";

export const DEFAULT_COMPARE_COLS: readonly CompareOptionalColumn[] = [
  "ci",
  "score",
];

const COL_SET = new Set<string>(DEFAULT_COMPARE_COLS);

export function parseCompareCols(
  raw: string | null,
): Set<CompareOptionalColumn> {
  if (raw === null) return new Set(DEFAULT_COMPARE_COLS);
  const out = new Set<CompareOptionalColumn>();
  for (const part of raw.split(",")) {
    const key = part.trim().toLowerCase();
    if (COL_SET.has(key)) out.add(key as CompareOptionalColumn);
  }
  return out;
}

export function serializeCompareCols(cols: Set<CompareOptionalColumn>): string | null {
  const ordered = DEFAULT_COMPARE_COLS.filter((c) => cols.has(c));
  if (
    ordered.length === DEFAULT_COMPARE_COLS.length &&
    DEFAULT_COMPARE_COLS.every((c) => cols.has(c))
  ) {
    return null;
  }
  return ordered.join(",");
}

export function parseDetailsOpen(raw: string | null): boolean {
  return raw === "1" || raw === "true";
}
