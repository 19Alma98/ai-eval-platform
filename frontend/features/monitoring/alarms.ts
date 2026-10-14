import type { MetricMonitor } from "@/lib/api/types";

/** Max acceptable fail rate (0–1) per metric key; above it the metric is in alarm. */
export type AlarmThresholds = Record<string, number>;

export const DEFAULT_ALARM_FAIL_RATE = 0.2;

export function metricKey(metric: Pick<MetricMonitor, "name" | "source">): string {
  return `${metric.source}:${metric.name}`;
}

export function parseAlarmThresholds(raw: string | null): AlarmThresholds {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: AlarmThresholds = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value === "number" && value >= 0 && value <= 1) out[key] = value;
    }
    return out;
  } catch {
    return {};
  }
}

/** Fail rate of the most recent bucket that saw traffic. */
export function latestFailRate(metric: MetricMonitor): number | null {
  for (let i = metric.series.length - 1; i >= 0; i--) {
    const bucket = metric.series[i];
    if (bucket.n > 0 && bucket.fail_rate != null) return bucket.fail_rate;
  }
  return null;
}

export type AlarmState = {
  limit: number;
  windowRate: number | null;
  latestRate: number | null;
  firing: boolean;
};

export function alarmState(metric: MetricMonitor, thresholds: AlarmThresholds): AlarmState {
  const limit = thresholds[metricKey(metric)] ?? DEFAULT_ALARM_FAIL_RATE;
  const latestRate = latestFailRate(metric);
  const windowRate = metric.fail_rate;
  const firing =
    (windowRate != null && windowRate > limit) || (latestRate != null && latestRate > limit);
  return { limit, windowRate, latestRate, firing };
}
