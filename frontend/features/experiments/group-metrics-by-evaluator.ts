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
  /** 95% CI of the paired mean-score / pass-rate difference, when the backend sent one. */
  mean_ci: [number, number] | null;
  pass_rate_ci: [number, number] | null;
  status: string;
};

type MetricPair = {
  mean?: MetricComparison;
  pass?: MetricComparison;
};

function ciOf(m: MetricComparison | undefined): [number, number] | null {
  return m?.ci_low != null && m?.ci_high != null ? [m.ci_low, m.ci_high] : null;
}

/**
 * The backend flags a regression when either the mean score or the pass rate
 * drops significantly, so the row verdict is the worse of the two.
 */
export function combinedStatus(mean?: string, pass?: string): string {
  const statuses = [mean, pass].filter((s): s is string => s != null);
  for (const decisive of ["regression", "improved", "unchanged"]) {
    if (statuses.includes(decisive)) return decisive;
  }
  return mean ?? pass ?? "unavailable";
}

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
      mean_ci: ciOf(slot.mean),
      pass_rate_ci: ciOf(slot.pass),
      status: combinedStatus(slot.mean?.status, slot.pass?.status),
    });
  }

  return sortMetricsForDisplay(rows);
}
