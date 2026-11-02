import { metricLabel } from "@/lib/metrics-catalog";
import type { MatrixRow, MetricColumn } from "./experiment-matrix";
import { formatRunMetric, runMetricLabel } from "./experiment-meta";
import { isLowerBetter } from "./metric-direction";

/** A metric that can go on a chart axis: an evaluator score or a logged run metric. */
export type ChartMetric = {
  key: string;
  label: string;
  kind: MetricColumn["kind"];
  lowerIsBetter: boolean;
};

/** How points are grouped into colored series. */
export type ColorBy = "none" | "model" | "prompt" | `param:${string}`;

export type ChartPoint = {
  id: string;
  name: string;
  series: string;
  x: number;
  y: number;
};

export type ChartData = { series: string[]; points: ChartPoint[] };

const NO_VALUE = "(not set)";

export function chartMetrics(columns: MetricColumn[]): ChartMetric[] {
  return columns.map((col) => ({
    key: col.key,
    label: col.kind === "logged" ? runMetricLabel(col.label) : metricLabel(col.label),
    kind: col.kind,
    lowerIsBetter: isLowerBetter(col.kind === "logged" ? col.label : col.key),
  }));
}

/** Format a value of ``metric`` for ticks and tooltips. */
export function formatChartValue(metric: ChartMetric | undefined, value: number): string {
  if (!metric || metric.kind === "evaluator") return value.toFixed(2);
  return formatRunMetric(metric.key.replace(/^logged:/, ""), value);
}

export function seriesOf(row: MatrixRow, colorBy: ColorBy): string {
  if (colorBy === "none") return "Experiments";
  if (colorBy === "model") return row.model ?? NO_VALUE;
  if (colorBy === "prompt") return row.prompt ?? NO_VALUE;
  return row.params[colorBy.slice("param:".length)] ?? NO_VALUE;
}

function collect(
  rows: MatrixRow[],
  colorBy: ColorBy,
  xOf: (row: MatrixRow) => number | null | undefined,
  yOf: (row: MatrixRow) => number | null | undefined,
): ChartData {
  const points: ChartPoint[] = [];
  const series: string[] = [];
  for (const row of rows) {
    const x = xOf(row);
    const y = yOf(row);
    if (x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
    const name = seriesOf(row, colorBy);
    if (!series.includes(name)) series.push(name);
    points.push({ id: row.experiment.id, name: row.label, series: name, x, y });
  }
  series.sort((a, b) => (a === NO_VALUE ? 1 : b === NO_VALUE ? -1 : a.localeCompare(b)));
  return { series, points: points.sort((a, b) => a.x - b.x) };
}

/** One point per experiment: x = creation time (ms), y = ``metricKey``. */
export function timeSeriesData(rows: MatrixRow[], metricKey: string, colorBy: ColorBy): ChartData {
  return collect(
    rows,
    colorBy,
    (row) => new Date(row.experiment.created_at).getTime(),
    (row) => row.metrics[metricKey]?.mean,
  );
}

/** One point per experiment with both metrics: x = ``xKey``, y = ``yKey``. */
export function tradeoffData(
  rows: MatrixRow[],
  xKey: string,
  yKey: string,
  colorBy: ColorBy,
): ChartData {
  return collect(
    rows,
    colorBy,
    (row) => row.metrics[xKey]?.mean,
    (row) => row.metrics[yKey]?.mean,
  );
}

/**
 * Points no other point beats on both axes (the best trade-offs), sorted by x.
 * ``xLower`` / ``yLower`` say which direction is better on each axis.
 */
export function paretoFront(points: ChartPoint[], xLower: boolean, yLower: boolean): ChartPoint[] {
  const atLeast = (a: number, b: number, lower: boolean) => (lower ? a <= b : a >= b);
  const strictly = (a: number, b: number, lower: boolean) => (lower ? a < b : a > b);
  const front = points.filter(
    (p) =>
      !points.some(
        (q) =>
          q !== p &&
          atLeast(q.x, p.x, xLower) &&
          atLeast(q.y, p.y, yLower) &&
          (strictly(q.x, p.x, xLower) || strictly(q.y, p.y, yLower)),
      ),
  );
  return front.sort((a, b) => a.x - b.x);
}

const PREFERRED_COST_KEYS = [
  "logged:cost_usd",
  "logged:opengrade.latency_p95_ms",
  "logged:opengrade.latency_p50_ms",
];

/**
 * Default trade-off axes: quality (first evaluator) on y against cost or latency on x,
 * falling back to any lower-is-better metric, then to a second evaluator.
 */
export function defaultTradeoffAxes(
  metrics: ChartMetric[],
): { x: string | null; y: string | null } {
  const y = metrics.find((m) => m.kind === "evaluator" && !m.lowerIsBetter)?.key ?? null;
  const has = (key: string) => metrics.some((m) => m.key === key);
  const x =
    PREFERRED_COST_KEYS.find(has) ??
    metrics.find((m) => m.lowerIsBetter && m.key !== y)?.key ??
    metrics.find((m) => m.key !== y)?.key ??
    null;
  return { x, y };
}

/** Color-by choices: model, prompt and every parameter that differs between experiments. */
export function colorByOptions(
  varying: Record<string, string[]>,
): { value: ColorBy; label: string }[] {
  return [
    { value: "none", label: "No grouping" },
    { value: "model", label: "Model" },
    { value: "prompt", label: "Prompt" },
    ...Object.keys(varying)
      .sort()
      .map((key) => ({ value: `param:${key}` as ColorBy, label: key })),
  ];
}

export function parseColorBy(raw: string | null, varying: Record<string, string[]>): ColorBy {
  if (raw === "model" || raw === "prompt" || raw === "none") return raw;
  if (raw?.startsWith("param:") && raw.slice(6) in varying) return raw as ColorBy;
  return "none";
}
