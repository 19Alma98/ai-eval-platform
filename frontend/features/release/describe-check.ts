import type { ReleaseCheckItemResponse } from "@/lib/api/types";
import { formatDeltaPoints, formatScore } from "@/lib/format";
import { metricLabel } from "@/lib/metrics-catalog";

export type CheckView = {
  key: string;
  title: string;
  actual: string;
  target: string;
  outcome: "passed" | "failed" | "unavailable";
  /** Regression checks link to the side-by-side comparison. */
  isRegression: boolean;
};

function ms(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
}

function outcomeOf(status: string): CheckView["outcome"] {
  const key = status.toLowerCase();
  if (key === "passed") return "passed";
  if (key === "failed") return "failed";
  return "unavailable";
}

/** Turn an API check id (`groundedness.min`, `latency.p95`, …) into a readable row. */
export function describeCheck(check: ReleaseCheckItemResponse): CheckView {
  const outcome = outcomeOf(check.status);
  const id = check.metric;

  if (id === "latency.p95") {
    return {
      key: id,
      title: "Latency (95% of answers)",
      actual: ms(check.actual),
      target: `≤ ${ms(check.threshold)}`,
      outcome,
      isRegression: false,
    };
  }
  if (id === "cost.max_per_request_usd") {
    return {
      key: id,
      title: "Average cost per answer",
      actual: check.actual == null ? "—" : `$${check.actual.toFixed(4)}`,
      target: check.threshold == null ? "—" : `≤ $${check.threshold.toFixed(4)}`,
      outcome,
      isRegression: false,
    };
  }
  if (id === "regression.max_delta") {
    return {
      key: id,
      title: "No drop vs baseline",
      actual: "Needs a baseline",
      target: `≥ ${formatDeltaPoints(check.threshold)}`,
      outcome,
      isRegression: true,
    };
  }
  const regression = /^regression\.(.+)\.mean_score$/.exec(id);
  if (regression) {
    return {
      key: id,
      title: `${metricLabel(regression[1])} vs baseline`,
      actual: formatDeltaPoints(check.actual),
      target: `no worse than ${formatDeltaPoints(check.threshold)}`,
      outcome,
      isRegression: true,
    };
  }
  const min = /^(.+)\.min$/.exec(id);
  const name = min ? min[1]! : id;
  return {
    key: id,
    title: `${metricLabel(name)} average score`,
    actual: formatScore(check.actual),
    target: `≥ ${formatScore(check.threshold)}`,
    outcome,
    isRegression: false,
  };
}

export type QualityBarRule = { name: string; enabled: boolean; min: string };

export type QualityBar = {
  rules: QualityBarRule[];
  latencyEnabled: boolean;
  latencySeconds: string;
  regressionEnabled: boolean;
  regressionPoints: string;
};

function num(value: string): number | null {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Form state → API policy object (same shape as the CI `opengrade.yaml`). */
export function policyFromQualityBar(bar: QualityBar): Record<string, unknown> {
  const policy: Record<string, unknown> = {};
  for (const rule of bar.rules) {
    const min = num(rule.min);
    if (rule.enabled && min !== null && rule.name !== "latency") {
      policy[rule.name] = { min };
    }
  }
  const seconds = num(bar.latencySeconds);
  if (bar.latencyEnabled && seconds !== null) {
    policy.latency = { p95_max_ms: Math.round(seconds * 1000) };
  }
  const points = num(bar.regressionPoints);
  if (bar.regressionEnabled && points !== null) {
    policy.regression = { max_delta: -Math.abs(points) / 100 };
  }
  return policy;
}
