import { isLowerBetter } from "@/features/experiments/metric-direction";
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

/** Run metrics (`cost_usd`, `latency_p50_ms`, …) are arbitrary numbers, not 0–1 scores. */
function rawNumber(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
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
      target:
        check.threshold == null
          ? "no significant drop (95% CI)"
          : `no significant drop; mean floor ${formatDeltaPoints(check.threshold)}`,
      outcome,
      isRegression: true,
    };
  }
  const groupRegression = /^groups\.(.+)=(.+)\.regression\.(.+)\.mean_score$/.exec(id);
  if (groupRegression) {
    const [, by, value, metric] = groupRegression;
    return {
      key: id,
      title: `${metricLabel(metric!)} in ${by}=${value} vs baseline`,
      actual: formatDeltaPoints(check.actual),
      target:
        check.threshold == null
          ? "no significant drop (95% CI)"
          : `no significant drop (95% CI); mean floor ${formatDeltaPoints(check.threshold)}`,
      outcome,
      isRegression: true,
    };
  }
  const groupMin = /^groups\.(.+)=(.+)\.(.+)\.min$/.exec(id);
  if (groupMin) {
    const [, by, value, metric] = groupMin;
    return {
      key: id,
      title: `${metricLabel(metric!)} in ${by}=${value}`,
      actual: formatScore(check.actual),
      target: `≥ ${formatScore(check.threshold)}`,
      outcome,
      isRegression: false,
    };
  }
  const regression = /^regression\.(.+)\.mean_score$/.exec(id);
  if (regression) {
    return {
      key: id,
      title: `${metricLabel(regression[1])} vs baseline`,
      actual: formatDeltaPoints(check.actual),
      target:
        check.threshold == null
          ? "no significant drop (95% CI)"
          : `no significant drop (95% CI); mean floor ${formatDeltaPoints(check.threshold)}`,
      outcome,
      isRegression: true,
    };
  }
  const runMetric = /^experiment_metrics\.(.+)\.(min|max)$/.exec(id);
  if (runMetric) {
    return {
      key: id,
      title: `Run metric ${runMetric[1]}`,
      actual: rawNumber(check.actual),
      target: `${runMetric[2] === "max" ? "≤" : "≥"} ${rawNumber(check.threshold)}`,
      outcome,
      isRegression: false,
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

export type ExperimentMetricRule = {
  key: string;
  enabled: boolean;
  bound: string;
};

export type QualityBar = {
  rules: QualityBarRule[];
  latencyEnabled: boolean;
  latencySeconds: string;
  regressionEnabled: boolean;
  regressionPoints: string;
  costEnabled: boolean;
  costMaxUsd: string;
  experimentMetricRules: ExperimentMetricRule[];
  groupsEnabled: boolean;
  groupsBy: string;
  groupsMinItems: string;
  groupsMaxDeltaPoints: string;
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
  if (bar.regressionEnabled) {
    const points = num(bar.regressionPoints);
    policy.regression =
      points !== null ? { max_delta: -Math.abs(points) / 100 } : {};
  }
  const costMax = num(bar.costMaxUsd);
  if (bar.costEnabled && costMax !== null) {
    policy.cost = { max_per_request_usd: costMax };
  }
  const experimentMetrics: Record<string, { min?: number; max?: number }> = {};
  for (const rule of bar.experimentMetricRules) {
    const bound = num(rule.bound);
    if (!rule.enabled || bound === null) continue;
    experimentMetrics[rule.key] = isLowerBetter(rule.key) ? { max: bound } : { min: bound };
  }
  if (Object.keys(experimentMetrics).length > 0) {
    policy.experiment_metrics = experimentMetrics;
  }
  if (bar.groupsEnabled && bar.groupsBy.trim()) {
    const groups: Record<string, unknown> = { by: bar.groupsBy.trim() };
    const minItems = num(bar.groupsMinItems);
    if (minItems !== null && Number.isInteger(minItems) && minItems >= 1) {
      groups.min_items = minItems;
    }
    const groupPoints = num(bar.groupsMaxDeltaPoints);
    if (groupPoints !== null) {
      groups.max_delta = -Math.abs(groupPoints) / 100;
    }
    policy.groups = groups;
  }
  return policy;
}
