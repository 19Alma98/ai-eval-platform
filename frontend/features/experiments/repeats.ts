import type { EvaluationResult, ExperimentItemOutput } from "@/lib/api/types";

/** Per-item summary of repeated runs, mirroring the server's `metadata.repeats`. */
export type RepeatStats = {
  n: number;
  passRate: number;
  flaky: boolean;
};

function isSkipped(result: EvaluationResult): boolean {
  return (result.label ?? "").trim().toUpperCase() === "SKIPPED";
}

function isPass(result: EvaluationResult): boolean {
  return (result.label ?? "").trim().toUpperCase() === "PASS";
}

/**
 * One result per item. With repeats: mean score over applicable repeats, PASS when at
 * least half passed (same rule as the server's per-item compare). A single result is
 * returned unchanged.
 */
export function collapseResultsByItem(
  results: EvaluationResult[],
): Map<string, EvaluationResult> {
  const groups = new Map<string, EvaluationResult[]>();
  for (const result of results) {
    const rows = groups.get(result.dataset_item_id) ?? [];
    rows.push(result);
    groups.set(result.dataset_item_id, rows);
  }
  const collapsed = new Map<string, EvaluationResult>();
  for (const [itemId, rows] of groups) {
    rows.sort((a, b) => (a.repeat ?? 0) - (b.repeat ?? 0));
    if (rows.length === 1) {
      collapsed.set(itemId, rows[0]);
      continue;
    }
    const applicable = rows.filter((r) => !isSkipped(r));
    if (applicable.length === 0) {
      collapsed.set(itemId, rows[0]);
      continue;
    }
    const scores = applicable.map((r) => r.score ?? 0);
    const mean = scores.reduce((sum, v) => sum + v, 0) / scores.length;
    const passRate = applicable.filter(isPass).length / applicable.length;
    const failing = applicable.find((r) => !isPass(r)) ?? applicable[0];
    const stats: RepeatStats = {
      n: rows.length,
      passRate,
      flaky: passRate > 0 && passRate < 1,
    };
    collapsed.set(itemId, {
      ...failing,
      score: mean,
      label: passRate >= 0.5 ? "PASS" : "FAIL",
      metadata: { ...failing.metadata, repeats: stats },
    });
  }
  return collapsed;
}

/** First repeat's output per item (what an item row shows). */
export function firstOutputByItem(
  outputs: ExperimentItemOutput[],
): Map<string, ExperimentItemOutput> {
  const byItem = new Map<string, ExperimentItemOutput>();
  for (const output of [...outputs].sort((a, b) => (a.repeat ?? 0) - (b.repeat ?? 0))) {
    if (!byItem.has(output.dataset_item_id)) byItem.set(output.dataset_item_id, output);
  }
  return byItem;
}

/** Repeat stats from a result's metadata, client- or server-collapsed. */
export function repeatStatsOf(metadata: Record<string, unknown> | undefined): RepeatStats | null {
  const raw = metadata?.repeats;
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const n = typeof record.n === "number" ? record.n : null;
  const passRate =
    typeof record.passRate === "number"
      ? record.passRate
      : typeof record.pass_rate === "number"
        ? record.pass_rate
        : null;
  if (n === null || passRate === null) return null;
  return { n, passRate, flaky: record.flaky === true };
}
