import type {
  LiveSeriesBucket,
  MetricMonitor,
  ProjectOverview,
} from "@/lib/api/types";
import { formatDeltaPoints, formatPercent as formatPercentRate } from "@/lib/format";
import { metricLabel } from "@/lib/metrics-catalog";
import { alarmState, type AlarmThresholds } from "@/features/monitoring/alarms";

export const OVERVIEW_ATTENTION_LIMIT = 8;

const OVERVIEW_WARNING_MESSAGES: Record<string, string> = {
  compare_unavailable:
    "Offline compare is temporarily unavailable; experiment cards may be incomplete.",
  calibration_unavailable:
    "Judge calibration could not be loaded; calibration alerts are hidden.",
  live_truncated:
    "This time range has more than 10,000 live interactions; KPIs and charts may undercount.",
};

export function overviewWarningMessages(warnings: string[]): string[] {
  const seen = new Set<string>();
  const messages: string[] = [];
  for (const code of warnings) {
    const message = OVERVIEW_WARNING_MESSAGES[code] ?? code;
    if (seen.has(message)) continue;
    seen.add(message);
    messages.push(message);
  }
  return messages;
}

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
      name: metricLabel(m.name),
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
  hint?: string;
  tone?: "ok" | "fail" | "neutral";
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
  const failRate = formatPercent(live.fail_rate, live.n_interactions);

  return {
    live: [
      {
        label: "Questions answered",
        value: String(live.n_interactions),
        href: "/live-runs",
        hint: "Live questions received in this time range",
      },
      {
        label: "Failing answers",
        value: failRate,
        href: "/live-runs?failed=1",
        hint: "Judge fail, failing SDK metric, or thumbs-down",
        tone:
          live.n_interactions === 0 || live.fail_rate == null
            ? "neutral"
            : live.fail_rate > 0
              ? "fail"
              : "ok",
      },
      {
        label: "Average quality",
        value: formatScore(live.mean_score),
        href: "/live-runs",
        hint: "Mean judge score from 0 (bad) to 1 (good)",
      },
      {
        label: "Waiting for judge",
        value: String(live.n_pending),
        href: "/live-runs",
        hint: "Answers not scored yet",
      },
    ],
    offline: [
      {
        label: "Test sets",
        value: String(offline.n_datasets),
        href: "/datasets",
        hint: "Questions with expected answers",
      },
      {
        label: "Metrics",
        value: offline.metrics_set
          ? `${offline.metrics_set.name} · v${offline.metrics_set.version}`
          : "Not set up",
        href: "/metrics",
        hint: "What every experiment is scored on",
      },
      {
        label: "Latest experiment",
        value: latest?.name ?? "None yet",
        href: latest ? `/experiments/${latest.id}` : "/experiments",
        hint: "Most recent run of your app on a test set",
      },
      {
        label: "Release gate",
        value: offline.release_ready ? "Ready to check" : "Not ready",
        href: "/release",
        hint: offline.release_ready
          ? "Check the latest experiment against your quality bar"
          : "Finish an experiment first",
      },
    ],
  };
}

export function regressionDrillDownHref(
  offline: ProjectOverview["offline"],
): string {
  const compare = offline.compare;
  if (compare?.candidate_experiment_id && compare.baseline_experiment_id) {
    const candidate = encodeURIComponent(compare.candidate_experiment_id);
    const baseline = encodeURIComponent(compare.baseline_experiment_id);
    return `/experiments/${candidate}/compare?baseline=${baseline}`;
  }
  const latest = offline.latest_experiment;
  if (latest) {
    return `/experiments/${latest.id}`;
  }
  return "/experiments";
}

export type AttentionRowKind = "live_fail" | "regression" | "calibration" | "metric_alarm";

export type AttentionRow = {
  id: string;
  kind: AttentionRowKind;
  title: string;
  subtitle?: string;
  href?: string;
  createdAt?: string;
};

function metricAlarmTitle(metric: MetricMonitor): string {
  const name = metric.source === "judge" ? metricLabel(metric.name) : metric.name;
  const source =
    metric.source === "judge"
      ? "LLM judge"
      : metric.source === "human"
        ? "user feedback"
        : "SDK";
  return `Alarm on ${name} (${source})`;
}

export function mergeAttentionItems(
  overview: ProjectOverview,
  options?: {
    metrics?: MetricMonitor[];
    alarmThresholds?: AlarmThresholds;
  },
): AttentionRow[] {
  const rows: AttentionRow[] = [];

  for (const item of overview.live.attention) {
    rows.push({
      id: `live-${item.interaction_id}`,
      kind: "live_fail",
      title: item.question,
      subtitle:
        item.reason === "fail"
          ? "Judge fail, failing SDK metric, or thumbs-down"
          : item.reason,
      href: `/live-runs/${item.interaction_id}`,
      createdAt: item.created_at,
    });
  }

  const regressionHref = regressionDrillDownHref(overview.offline);

  for (const regression of overview.offline.regressions) {
    rows.push({
      id: `regression-${regression.name}`,
      kind: "regression",
      title: `${metricLabel(regression.name)} got worse`,
      subtitle:
        regression.delta != null
          ? `${formatDeltaPoints(regression.delta)} vs baseline`
          : regression.status,
      href: regressionHref,
    });
  }

  for (const alert of overview.calibration_alerts) {
    rows.push({
      id: `calibration-${alert.kind}`,
      kind: "calibration",
      title: `Reviewers often disagree with the ${metricLabel(alert.kind)} judge`,
      subtitle: `${(alert.agreement_rate * 100).toFixed(0)}% agreement across ${alert.n_reviewed} reviews`,
    });
  }

  const thresholds = options?.alarmThresholds ?? {};
  for (const metric of options?.metrics ?? []) {
    if (!alarmState(metric, thresholds).firing) continue;
    const rate = metric.fail_rate;
    rows.push({
      id: `metric-alarm-${metric.source}-${metric.name}`,
      kind: "metric_alarm",
      title: metricAlarmTitle(metric),
      subtitle:
        rate != null
          ? `${formatPercentRate(rate)} fail rate · n=${metric.n} in range`
          : `n=${metric.n} in range`,
      href: "/monitoring",
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
      title: "1. Add a test set",
      measure: "Questions your app must answer well, with expected answers and source documents.",
      status: nDatasets === 0 ? "empty" : "ready",
      summary:
        nDatasets === 0
          ? "No test sets yet"
          : `${nDatasets} test set${nDatasets === 1 ? "" : "s"}`,
      href: "/datasets",
      cta: "Create test set",
    },
    {
      title: "2. Choose metrics",
      measure: "What “good” means: correctness, groundedness, retrieval quality and their thresholds.",
      status: metricsSet ? "ready" : "empty",
      summary: metricsSet ? `${metricsSet.name} · v${metricsSet.version}` : "Not set up",
      href: "/metrics",
      cta: "Set up metrics",
    },
    {
      title: "3. Run an experiment",
      measure: "Run your app on the test set and score every answer.",
      status: latest ? "ready" : "empty",
      summary: latest ? latest.name : "No experiments yet",
      href: latest ? `/experiments/${latest.id}` : "/experiments",
      cta: "New experiment",
    },
    {
      title: "4. Check the release",
      measure: "Compare against your baseline and decide if it is safe to ship.",
      status: offline.release_ready ? "ready" : "empty",
      summary: offline.release_ready ? "Ready to check" : "Needs a finished experiment",
      href: "/release",
      cta: "Open release gate",
    },
  ];
}
