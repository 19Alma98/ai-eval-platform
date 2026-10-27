import type {
  LiveSeriesBucket,
  MetricMonitor,
  ProjectOverview,
} from "@/lib/api/types";
import { formatDeltaPoints, formatPercent as formatPercentRate } from "@/lib/format";
import { metricLabel, metricsSetDisplayName } from "@/lib/metrics-catalog";
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

export type StatusTone = "ok" | "fail" | "neutral";

export type StatusStat = { label: string; value: string; href?: string };

export type StatusAction = { label: string; href: string };

/** One of the two Overview headline panels: a verdict first, supporting numbers after. */
export type StatusPanel = {
  eyebrow: string;
  headline: string;
  tone: StatusTone;
  detail: string;
  stats: StatusStat[];
  primary: StatusAction | null;
  secondary: StatusAction | null;
};

const RANGE_PHRASES: Record<string, string> = {
  "15m": "last 15 minutes",
  "1h": "last hour",
  "6h": "last 6 hours",
  "24h": "last 24 hours",
  "7d": "last 7 days",
};

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

const SMALL_NUMBERS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];

/** Headlines read as sentences: "Two metrics got worse." rather than "2 metrics got worse". */
function spelledPlural(n: number, word: string): string {
  const count = SMALL_NUMBERS[n] ?? String(n);
  return `${count} ${word}${n === 1 ? "" : "s"}`;
}

/** "Before release": the latest experiment against its baseline. */
export function buildReleasePanel(overview: ProjectOverview): StatusPanel {
  const { offline } = overview;
  const latest = offline.latest_experiment;
  const compare = offline.compare;
  const metricsLabel = offline.metrics_set
    ? `${metricsSetDisplayName(offline.metrics_set.name)} · v${offline.metrics_set.version}`
    : "Not set up";
  const stats: StatusStat[] = [
    { label: "Test sets", value: String(offline.n_datasets), href: "/datasets" },
    { label: "Metrics", value: metricsLabel, href: "/metrics" },
  ];
  const gate: StatusAction = { label: "Run quality gate", href: "/release" };

  if (!latest) {
    return {
      eyebrow: "Before release",
      headline: "No experiments yet.",
      tone: "neutral",
      detail:
        offline.n_datasets === 0
          ? "Add a test set, then run your app on it to get a score for every answer."
          : "Run your app on a test set to get a score for every answer.",
      stats,
      primary:
        offline.n_datasets === 0
          ? { label: "Create test set", href: "/datasets" }
          : { label: "New experiment", href: "/experiments?new=1" },
      secondary: null,
    };
  }

  const experimentHref = `/experiments/${encodeURIComponent(latest.id)}`;
  const passRates = compare?.metrics.filter((m) => m.metric === "pass_rate") ?? [];
  if (!compare || passRates.length === 0) {
    return {
      eyebrow: "Before release",
      headline: "No baseline to compare.",
      tone: "neutral",
      detail: `${latest.name} finished. Compare it with an earlier experiment to see what improved.`,
      stats,
      primary: { label: "Open experiment", href: experimentHref },
      secondary: offline.release_ready ? gate : null,
    };
  }

  const worse = offline.regressions.length;
  const better = passRates.filter((m) => m.status === "improved").length;
  const candidates = passRates.map((m) => m.candidate).filter((v): v is number => v != null);
  const avgPass = candidates.length
    ? candidates.reduce((sum, v) => sum + v, 0) / candidates.length
    : null;
  const compareAction: StatusAction = {
    label: worse > 0 ? "See what got worse" : "See comparison",
    href: regressionDrillDownHref(offline),
  };

  return {
    eyebrow: "Before release",
    headline: worse > 0 ? `${spelledPlural(worse, "metric")} got worse.` : "Nothing got worse.",
    tone: worse > 0 ? "fail" : "ok",
    detail: `${latest.name} vs its baseline: ${better} better, ${worse} worse, ${
      passRates.length - better - worse
    } unchanged.`,
    stats: [
      { label: "Avg. pass rate", value: formatPercentRate(avgPass), href: experimentHref },
      ...stats,
    ],
    primary: worse > 0 ? compareAction : gate,
    secondary: worse > 0 ? gate : compareAction,
  };
}

/** "In production": live answers scored in the selected time range. */
export function buildLivePanel(overview: ProjectOverview, preset: string): StatusPanel {
  const { live } = overview;
  const range = RANGE_PHRASES[preset] ?? "selected range";

  if (live.n_interactions === 0) {
    return {
      eyebrow: "In production",
      headline: "No live traffic.",
      tone: "neutral",
      detail: `No questions in the ${range}. Send production traffic with the SDK and the judge scores every answer.`,
      stats: [{ label: "Waiting for judge", value: String(live.n_pending), href: "/live-runs" }],
      primary: { label: "Open live answers", href: "/live-runs" },
      secondary: null,
    };
  }

  const failing = live.n_failed > 0;
  return {
    eyebrow: "In production",
    headline: failing
      ? `${formatPercentRate(live.fail_rate)} of answers are failing.`
      : "Every answer passed.",
    tone: failing ? "fail" : "ok",
    detail: failing
      ? `${live.n_failed} of ${plural(live.n_interactions, "question")} in the ${range} failed the judge, an SDK metric or got a thumbs-down.`
      : `${plural(live.n_interactions, "question")} in the ${range}, none failing.`,
    stats: [
      { label: "Questions", value: String(live.n_interactions), href: "/live-runs" },
      {
        label: "Avg. quality",
        value: live.mean_score == null ? "—" : live.mean_score.toFixed(2),
        href: "/live-runs",
      },
      { label: "Waiting for judge", value: String(live.n_pending), href: "/live-runs" },
    ],
    primary: failing
      ? { label: "Review failing answers", href: "/live-runs?failed=1" }
      : { label: "Open live answers", href: "/live-runs" },
    secondary: { label: "Production health", href: "/monitoring" },
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
      title: "Add a test set",
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
      title: "Choose metrics",
      measure: "What “good” means: correctness, groundedness, retrieval quality and their thresholds.",
      status: metricsSet ? "ready" : "empty",
      summary: metricsSet
        ? `${metricsSetDisplayName(metricsSet.name)} · v${metricsSet.version}`
        : "Not set up",
      href: "/metrics",
      cta: "Set up metrics",
    },
    {
      title: "Run an experiment",
      measure: "Run your app on the test set and score every answer.",
      status: latest ? "ready" : "empty",
      summary: latest ? latest.name : "No experiments yet",
      href: latest ? `/experiments/${latest.id}` : "/experiments",
      cta: "New experiment",
    },
    {
      title: "Run the quality gate",
      measure: "Compare against your baseline and decide if quality is good enough.",
      status: offline.release_ready ? "ready" : "empty",
      summary: offline.release_ready ? "Ready to check" : "Needs a finished experiment",
      href: "/release",
      cta: "Open quality gate",
    },
  ];
}
