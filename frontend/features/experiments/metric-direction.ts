/**
 * Heuristic: latency, cost, error and token keys are lower-is-better.
 * Strips a leading `logged:` prefix used by the experiments matrix and the
 * `opengrade.` prefix of run metrics the SDK logs (`opengrade.error_rate`).
 */
export function isLowerBetter(key: string): boolean {
  const k = key
    .replace(/^logged:/i, "")
    .toLowerCase()
    .replace(/^opengrade\./, "");
  return (
    k === "latency" ||
    k === "cost" ||
    k.startsWith("latency") ||
    k.startsWith("cost") ||
    k.startsWith("error") ||
    k.startsWith("tokens") ||
    k.endsWith("error_rate") ||
    k.endsWith("_ms") ||
    k.endsWith("_usd") ||
    k.endsWith("_tokens")
  );
}

export type DeltaTone = "better" | "worse" | "neutral";

/** Color hint for a candidate−baseline delta. */
export function deltaTone(
  delta: number | null | undefined,
  lowerIsBetter: boolean,
): DeltaTone {
  if (delta == null || Number.isNaN(delta) || Math.abs(delta) < 1e-9) {
    return "neutral";
  }
  const improved = lowerIsBetter ? delta < 0 : delta > 0;
  return improved ? "better" : "worse";
}
