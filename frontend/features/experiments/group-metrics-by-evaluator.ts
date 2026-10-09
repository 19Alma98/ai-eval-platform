import type { MetricComparison } from "@/lib/api/types";
import { sortMetricsForDisplay } from "./sort-metrics";

export type EvaluatorCompareRow = {
  evaluator_id: string;
  evaluator_name: string | null;
  candidate_mean: number | null;
  candidate_pass_rate: number | null;
  baseline_mean: number | null;
  baseline_pass_rate: number | null;
  delta: number | null;
  status: string;
};

type MetricPair = {
  mean?: MetricComparison;
  pass?: MetricComparison;
};

export function groupMetricsByEvaluator(
  metrics: MetricComparison[],
): EvaluatorCompareRow[] {
  const byEval = new Map<string, MetricPair>();

  for (const m of metrics) {
    const slot = byEval.get(m.evaluator_id) ?? {};
    if (m.metric === "mean_score") {
      slot.mean = m;
    } else if (m.metric === "pass_rate") {
      slot.pass = m;
    }
    byEval.set(m.evaluator_id, slot);
  }

  const rows: EvaluatorCompareRow[] = [];
  for (const [evaluator_id, slot] of byEval) {
    const primary = slot.mean ?? slot.pass;
    if (!primary) continue;
    rows.push({
      evaluator_id,
      evaluator_name: primary.evaluator_name,
      candidate_mean: slot.mean?.candidate ?? null,
      candidate_pass_rate: slot.pass?.candidate ?? null,
      baseline_mean: slot.mean?.baseline ?? null,
      baseline_pass_rate: slot.pass?.baseline ?? null,
      delta: slot.mean?.delta ?? null,
      status: slot.mean?.status ?? "unavailable",
    });
  }

  return sortMetricsForDisplay(rows);
}
