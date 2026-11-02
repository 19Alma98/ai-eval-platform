import type { ExperimentMetricComparison } from "@/lib/api/types";
import { formatRunMetric, runMetricLabel } from "./experiment-meta";
import { deltaTone, isLowerBetter, type DeltaTone } from "./metric-direction";

export type RunMetricChange = {
  key: string;
  label: string;
  candidate: string;
  baseline: string;
  /** "+12%" / "−3.4%" relative to the baseline, or the absolute delta when the baseline is 0. */
  change: string | null;
  tone: DeltaTone;
  lowerIsBetter: boolean;
};

/** Relative change of ``candidate`` vs ``baseline`` (null when not computable). */
export function relativeChange(candidate: number | null, baseline: number | null): number | null {
  if (candidate == null || baseline == null || baseline === 0) return null;
  return (candidate - baseline) / Math.abs(baseline);
}

function signed(text: string, value: number): string {
  if (Math.abs(value) < 1e-12) return text;
  return value > 0 ? `+${text}` : `−${text}`;
}

/**
 * Experiment-level metrics (cost, latency, error rate, anything from ``log_metrics``) with
 * their change vs the baseline, SDK run metrics first. Rates are compared in points, the
 * rest in percent.
 */
export function runMetricChanges(rows: ExperimentMetricComparison[]): RunMetricChange[] {
  const out = rows.map((row) => {
    const lower = isLowerBetter(row.key);
    const isRate = row.key.endsWith("error_rate");
    let change: string | null = null;
    if (row.delta != null && row.candidate != null && row.baseline != null) {
      const rel = relativeChange(row.candidate, row.baseline);
      if (isRate) {
        change = signed(`${(Math.abs(row.delta) * 100).toFixed(1)} pts`, row.delta);
      } else if (rel != null) {
        change = signed(`${(Math.abs(rel) * 100).toFixed(rel !== 0 && Math.abs(rel) < 0.1 ? 1 : 0)}%`, rel);
      } else {
        change = signed(formatRunMetric(row.key, Math.abs(row.delta)), row.delta);
      }
    }
    return {
      key: row.key,
      label: runMetricLabel(row.key),
      candidate: formatRunMetric(row.key, row.candidate),
      baseline: formatRunMetric(row.key, row.baseline),
      change,
      tone: deltaTone(row.delta, lower),
      lowerIsBetter: lower,
    };
  });
  const builtIn = (key: string) => (key.startsWith("opengrade.") ? 0 : 1);
  return out.sort((a, b) => builtIn(a.key) - builtIn(b.key) || a.label.localeCompare(b.label));
}
