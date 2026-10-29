import type { AlertMetric, AlertRule } from "@/lib/api/types";

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

export function metricOption(metric: AlertMetric): MetricOption {
  return ALERT_METRICS.find((m) => m.value === metric) ?? ALERT_METRICS[0];
}

/** Threshold as typed in the form (percent → 0–100). */
export function thresholdToInput(metric: AlertMetric, value: number): string {
  const unit = metricOption(metric).unit;
  return String(unit === "percent" ? Math.round(value * 1000) / 10 : value);
}

export function thresholdFromInput(metric: AlertMetric, raw: string): number | null {
  const n = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(n)) return null;
  return metricOption(metric).unit === "percent" ? n / 100 : n;
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

function windowLabel(minutes: number): string {
  return WINDOW_OPTIONS.find((w) => w.minutes === minutes)?.label ?? `${minutes} minutes`;
}

/** "groundedness (judge) fail rate > 20.0% over 1 hour" */
export function describeRule(
  rule: Pick<
    AlertRule,
    "metric" | "operator" | "threshold" | "window_minutes" | "score_name" | "score_source"
  > &
    Partial<Pick<AlertRule, "environment" | "version">>,
): string {
  const option = metricOption(rule.metric);
  const subject = option.needsScore
    ? `${rule.score_name ?? "?"}${rule.score_source ? ` (${rule.score_source})` : ""} ${option.unit === "percent" ? "fail rate" : "mean"}`
    : option.label.toLowerCase();
  const op = rule.operator === "gt" ? ">" : "<";
  const scope = [
    rule.environment ? `env ${rule.environment}` : null,
    rule.version ? `version ${rule.version}` : null,
  ].filter(Boolean);
  return `${subject} ${op} ${formatAlertValue(rule.metric, rule.threshold)} over ${windowLabel(rule.window_minutes)}${scope.length ? ` (${scope.join(", ")})` : ""}`;
}
