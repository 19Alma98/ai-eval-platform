import type { AlertCondition, AlertMetric, AlertRule } from "@/lib/api/types";

export type MetricOption = {
  value: AlertMetric;
  label: string;
  /** Unit the threshold is typed in; percent values are stored as 0–1. */
  unit: "percent" | "ms" | "usd" | "count" | "score";
  defaultOperator: "gt" | "lt";
  defaultThreshold: number;
  needsScore?: boolean;
};

export const ALERT_METRICS: MetricOption[] = [
  { value: "score_fail_rate", label: "Score fail rate", unit: "percent", defaultOperator: "gt", defaultThreshold: 0.2, needsScore: true },
  { value: "score_mean", label: "Score mean", unit: "score", defaultOperator: "lt", defaultThreshold: 0.7, needsScore: true },
  { value: "error_rate", label: "Error rate", unit: "percent", defaultOperator: "gt", defaultThreshold: 0.05 },
  { value: "latency_p90_ms", label: "Latency p90", unit: "ms", defaultOperator: "gt", defaultThreshold: 5000 },
  { value: "latency_p99_ms", label: "Latency p99", unit: "ms", defaultOperator: "gt", defaultThreshold: 10000 },
  { value: "latency_p50_ms", label: "Latency p50", unit: "ms", defaultOperator: "gt", defaultThreshold: 2000 },
  { value: "traffic", label: "Traces (traffic)", unit: "count", defaultOperator: "lt", defaultThreshold: 1 },
  { value: "cost_usd", label: "Cost", unit: "usd", defaultOperator: "gt", defaultThreshold: 10 },
  { value: "total_tokens", label: "Tokens", unit: "count", defaultOperator: "gt", defaultThreshold: 1_000_000 },
  { value: "needs_review", label: "Answers awaiting review", unit: "count", defaultOperator: "gt", defaultThreshold: 50 },
];

export const WINDOW_OPTIONS = [
  { minutes: 15, label: "15 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 360, label: "6 hours" },
  { minutes: 1440, label: "24 hours" },
  { minutes: 10080, label: "7 days" },
];

export const CONDITION_OPTIONS: { value: AlertCondition; label: string; hint: string }[] = [
  { value: "threshold", label: "Fixed threshold", hint: "The metric crosses a number you set." },
  {
    value: "change",
    label: "Change vs previous period (drift)",
    hint: "The metric moved by more than a percentage compared with the period before.",
  },
  {
    value: "anomaly",
    label: "Anomaly vs recent history",
    hint: "The metric is unusual compared with the same-size windows before it (z-score).",
  },
];

/** Comparison periods offered for change rules (minutes). */
export const BASELINE_OPTIONS = [
  { minutes: 0, label: "Same length as the window" },
  { minutes: 1440, label: "Previous 24 hours" },
  { minutes: 10080, label: "Previous 7 days" },
];

export function metricOption(metric: AlertMetric): MetricOption {
  return ALERT_METRICS.find((m) => m.value === metric) ?? ALERT_METRICS[0];
}

/** Threshold as typed in the form (percent → 0–100; change rules are % of change). */
export function thresholdToInput(
  metric: AlertMetric,
  value: number,
  condition: AlertCondition = "threshold",
): string {
  if (condition === "anomaly") return String(value);
  const percent = condition === "change" || metricOption(metric).unit === "percent";
  return String(percent ? Math.round(value * 1000) / 10 : value);
}

export function thresholdFromInput(
  metric: AlertMetric,
  raw: string,
  condition: AlertCondition = "threshold",
): number | null {
  const n = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(n)) return null;
  if (condition === "anomaly") return n;
  const percent = condition === "change" || metricOption(metric).unit === "percent";
  return percent ? n / 100 : n;
}

/** Default operator / threshold when a rule switches to ``condition``. */
export function conditionDefaults(
  metric: AlertMetric,
  condition: AlertCondition,
): { operator: "gt" | "lt" | "abs"; threshold: number } {
  const option = metricOption(metric);
  if (condition === "anomaly") return { operator: "abs", threshold: 3 };
  if (condition === "change") {
    return option.defaultOperator === "lt"
      ? { operator: "lt", threshold: -0.2 }
      : { operator: "gt", threshold: 0.2 };
  }
  return { operator: option.defaultOperator, threshold: option.defaultThreshold };
}

/**
 * Sign the threshold of change / anomaly rules by direction, so "goes down 20" is -20%
 * (a positive threshold with "below" would fire on almost every reading).
 */
export function signedThreshold(
  condition: AlertCondition,
  operator: "gt" | "lt" | "abs",
  value: number,
): number {
  if (condition === "threshold") return value;
  if (operator === "lt") return -Math.abs(value);
  return Math.abs(value);
}

/** What the rule compares: the metric, a relative change ("+12.0%") or a z-score. */
export function formatRuleValue(
  rule: Pick<AlertRule, "metric"> & { condition?: AlertCondition },
  value: number | null,
): string {
  if (value == null) return "no data";
  if (rule.condition === "change") return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
  if (rule.condition === "anomaly") return `z=${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
  return formatAlertValue(rule.metric, value);
}

/** "0.612 vs 0.801 baseline (−23.6%)" for change / anomaly rules; null otherwise. */
export function describeReading(
  rule: Pick<AlertRule, "metric" | "last_value"> & {
    condition?: AlertCondition;
    last_observed?: number | null;
    last_baseline?: number | null;
  },
): string | null {
  if (!rule.condition || rule.condition === "threshold") return null;
  if (rule.last_observed == null && rule.last_baseline == null) return null;
  return `${formatAlertValue(rule.metric, rule.last_observed ?? null)} vs ${formatAlertValue(rule.metric, rule.last_baseline ?? null)} baseline (${formatRuleValue(rule, rule.last_value)})`;
}

export function formatAlertValue(metric: AlertMetric, value: number | null): string {
  if (value == null) return "no data";
  switch (metricOption(metric).unit) {
    case "percent":
      return `${(value * 100).toFixed(1)}%`;
    case "ms":
      return `${Math.round(value).toLocaleString()} ms`;
    case "usd":
      return `$${value.toFixed(value < 1 ? 4 : 2)}`;
    case "score":
      return value.toFixed(3);
    default:
      return Math.round(value).toLocaleString();
  }
}

function periodLabel(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? "24 hours" : `${minutes / 1440} days`;
  if (minutes % 60 === 0) return `${minutes / 60} hours`;
  return `${minutes} minutes`;
}

function windowLabel(minutes: number): string {
  return WINDOW_OPTIONS.find((w) => w.minutes === minutes)?.label ?? `${minutes} minutes`;
}

/** "groundedness (judge) fail rate > 20.0% over 1 hour" */
export function describeRule(
  rule: Pick<
    AlertRule,
    "metric" | "operator" | "threshold" | "window_minutes" | "score_name" | "score_source"
  > &
    Partial<Pick<AlertRule, "environment" | "version" | "condition" | "baseline_minutes">>,
): string {
  const option = metricOption(rule.metric);
  const subject = option.needsScore
    ? `${rule.score_name ?? "?"}${rule.score_source ? ` (${rule.score_source})` : ""} ${option.unit === "percent" ? "fail rate" : "mean"}`
    : option.label.toLowerCase();
  const scope = [
    rule.environment ? `env ${rule.environment}` : null,
    rule.version ? `version ${rule.version}` : null,
  ].filter(Boolean);
  const suffix = scope.length ? ` (${scope.join(", ")})` : "";
  const window = windowLabel(rule.window_minutes);
  if (rule.condition === "change") {
    const pct = `${Math.abs(rule.threshold * 100).toFixed(1)}%`;
    const verb =
      rule.operator === "abs" ? "changes by more than" : rule.operator === "gt" ? "rises more than" : "drops more than";
    const baseline = rule.baseline_minutes ?? rule.window_minutes;
    const period =
      baseline === rule.window_minutes ? "the previous period" : `the previous ${periodLabel(baseline)}`;
    return `${subject} ${verb} ${pct} over ${window} vs ${period}${suffix}`;
  }
  if (rule.condition === "anomaly") {
    const z = Math.abs(rule.threshold).toFixed(1);
    const direction =
      rule.operator === "abs" ? "away from" : rule.operator === "gt" ? "above" : "below";
    const n = Math.floor((rule.baseline_minutes ?? 0) / rule.window_minutes);
    return `${subject} more than ${z}σ ${direction} the last ${n} windows of ${window}${suffix}`;
  }
  const op = rule.operator === "gt" ? ">" : "<";
  return `${subject} ${op} ${formatAlertValue(rule.metric, rule.threshold)} over ${window}${suffix}`;
}
