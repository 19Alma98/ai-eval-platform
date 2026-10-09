import type {
  LiveSeriesBucket,
  ProjectOverview,
} from "@/lib/api/types";

export const OVERVIEW_ATTENTION_LIMIT = 8;

export function shouldShowLiveChart(series: LiveSeriesBucket[]): boolean {
  const nonEmpty = series.filter((b) => b.n > 0).length;
  return nonEmpty >= 4;
}

export type PassRateBar = {
  name: string;
  candidate: number | null;
  baseline: number | null;
  delta: number | null;
  status: string;
  candidateExperimentId: string;
  baselineExperimentId: string;
};

export function mapPassRateBars(
  overview: ProjectOverview,
): PassRateBar[] | null {
  const compare = overview.offline.compare;
  if (!compare) return null;
  return compare.metrics
    .filter((m) => m.metric === "pass_rate")
    .map((m) => ({
      name: m.name,
      candidate: m.candidate,
      baseline: m.baseline,
      delta: m.delta,
      status: m.status,
      candidateExperimentId: compare.candidate_experiment_id,
      baselineExperimentId: compare.baseline_experiment_id,
    }));
}

export type DualKpiItem = {
  label: string;
  value: string;
  href: string;
};

export type DualKpiViewModel = {
  live: DualKpiItem[];
  offline: DualKpiItem[];
};

function formatPercent(rate: number | null, nInteractions: number): string {
  if (nInteractions === 0 || rate == null) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

function formatScore(score: number | null): string {
  if (score == null) return "—";
  return score.toFixed(2);
}

export function mapOverviewToDualKpi(
  overview: ProjectOverview,
): DualKpiViewModel {
  const { live, offline } = overview;
  const latest = offline.latest_experiment;

  return {
    live: [
      {
        label: "Interactions",
        value: String(live.n_interactions),
        href: "/live-runs",
      },
      {
        label: "Fail rate",
        value: formatPercent(live.fail_rate, live.n_interactions),
        href: "/live-runs",
      },
      {
        label: "In progress",
        value: String(live.n_pending),
        href: "/live-runs",
      },
      {
        label: "Mean score",
        value: formatScore(live.mean_score),
        href: "/live-runs",
      },
    ],
    offline: [
      {
        label: "Test sets",
        value: String(offline.n_datasets),
        href: "/datasets",
      },
      {
        label: "Metrics set",
        value: offline.metrics_set
          ? `${offline.metrics_set.name} v${offline.metrics_set.version}`
          : "—",
        href: "/metrics",
      },
      {
        label: "Last run",
        value: latest?.name ?? "—",
        href: latest ? `/experiments/${latest.id}` : "/experiments",
      },
      {
        label: "Release ready",
        value: offline.release_ready ? "Yes" : "No",
        href: "/release",
      },
    ],
  };
}

export type AttentionRowKind = "live_fail" | "regression" | "calibration";

export type AttentionRow = {
  id: string;
  kind: AttentionRowKind;
  title: string;
  subtitle?: string;
  href?: string;
  createdAt?: string;
};

export function mergeAttentionItems(
  overview: ProjectOverview,
): AttentionRow[] {
  const rows: AttentionRow[] = [];

  for (const item of overview.live.attention) {
    rows.push({
      id: `live-${item.interaction_id}`,
      kind: "live_fail",
      title: item.question,
      subtitle: item.reason,
      href: `/live-runs/${item.interaction_id}`,
      createdAt: item.created_at,
    });
  }

  for (const regression of overview.offline.regressions) {
    rows.push({
      id: `regression-${regression.name}`,
      kind: "regression",
      title: regression.name,
      subtitle:
        regression.delta != null
          ? `Δ ${regression.delta.toFixed(3)}`
          : regression.status,
    });
  }

  for (const alert of overview.calibration_alerts) {
    rows.push({
      id: `calibration-${alert.kind}`,
      kind: "calibration",
      title: alert.kind,
      subtitle: `${(alert.agreement_rate * 100).toFixed(0)}% agreement (${alert.n_reviewed} reviewed)`,
    });
  }

  return rows.slice(0, OVERVIEW_ATTENTION_LIMIT);
}

export type LoopCard = {
  title: string;
  measure: string;
  status: "empty" | "ready";
  summary: string;
  href: string;
  cta: string;
};

export function buildLoopCards(overview: ProjectOverview): LoopCard[] {
  const { offline } = overview;
  const nDatasets = offline.n_datasets;
  const metricsSet = offline.metrics_set;
  const latest = offline.latest_experiment;

  return [
    {
      title: "Test set",
      measure: "Reusable test cases (input + expected/actual).",
      status: nDatasets === 0 ? "empty" : "ready",
      summary:
        nDatasets === 0
          ? "No test sets yet."
          : `${nDatasets} test set${nDatasets === 1 ? "" : "s"}`,
      href: "/datasets",
      cta: nDatasets === 0 ? "Create test set" : "Open test set",
    },
    {
      title: "Metrics",
      measure: "Metrics sets — what you measure on each run.",
      status: metricsSet ? "ready" : "empty",
      summary: metricsSet
        ? `${metricsSet.name} v${metricsSet.version}`
        : "No default metrics set yet.",
      href: "/metrics",
      cta: metricsSet ? "Open metrics" : "Configure metrics",
    },
    {
      title: "Runs",
      measure: "Evaluation runs — scores per evaluator.",
      status: latest ? "ready" : "empty",
      summary: latest
        ? `${latest.name} (${latest.status})`
        : "No runs yet.",
      href: latest ? `/experiments/${latest.id}` : "/experiments",
      cta: latest ? "Open run" : "Create run",
    },
    {
      title: "Release readiness",
      measure: "PASS/FAIL against YAML thresholds.",
      status: offline.release_ready ? "ready" : "empty",
      summary: offline.release_ready
        ? "At least one completed run — ready to run release check."
        : "Complete a run before running release check.",
      href: "/release",
      cta: "Open release",
    },
  ];
}
