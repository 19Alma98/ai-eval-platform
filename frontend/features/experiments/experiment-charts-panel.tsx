"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { ArrowLeftRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { experimentHref } from "@/lib/links";
import {
  chartMetrics,
  colorByOptions,
  defaultTradeoffAxes,
  paretoFront,
  parseColorBy,
  timeSeriesData,
  tradeoffData,
  type ChartMetric,
} from "./experiment-charts";
import type { MatrixRow, MetricColumn } from "./experiment-matrix";

const chartLoading = (height: number) =>
  function ChartLoading() {
    return (
      <div className="animate-pulse rounded-md bg-surface-2" style={{ height }} aria-hidden />
    );
  };

const OverTimeChart = dynamic(
  () => import("./experiment-charts-inner").then((m) => m.MetricOverTimeChartInner),
  { ssr: false, loading: chartLoading(280) },
);
const TradeoffChart = dynamic(
  () => import("./experiment-charts-inner").then((m) => m.TradeoffChartInner),
  { ssr: false, loading: chartLoading(320) },
);

export type ChartMode = "time" | "tradeoff";

/** URL keys owned by the charts panel (kept with the matrix filters, so links reproduce a view). */
export const CHART_URL_KEYS = {
  mode: "chart",
  metric: "metric",
  x: "x",
  y: "y",
  color: "color",
} as const;

function MetricSelect({
  label,
  value,
  metrics,
  onChange,
}: {
  label: string;
  value: string | null;
  metrics: ChartMetric[];
  onChange: (value: string) => void;
}) {
  const evaluators = metrics.filter((m) => m.kind === "evaluator");
  const logged = metrics.filter((m) => m.kind === "logged");
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {label}
      <Select value={value ?? ""} onValueChange={(v) => v && onChange(String(v))}>
        <SelectTrigger className="h-8 min-w-[150px] text-xs" aria-label={label}>
          <SelectValue placeholder="Pick a metric" />
        </SelectTrigger>
        <SelectContent>
          {[...evaluators, ...logged].map((m) => (
            <SelectItem key={m.key} value={m.key} className="text-xs">
              {m.label}
              {m.kind === "logged" ? " · run metric" : ""}
              {m.lowerIsBetter ? " ↓" : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

function ColorSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      Color by
      <Select value={value} onValueChange={(v) => v && onChange(String(v))}>
        <SelectTrigger className="h-8 min-w-[130px] text-xs" aria-label="Color by">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value} className="text-xs">
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

/**
 * Charts over the experiments shown in the matrix (same filters): one metric over time,
 * or any two metrics against each other with the best trade-offs highlighted.
 */
export function ExperimentChartsPanel({
  rows,
  columns,
  varyingParams,
  projectId,
  searchParams,
  setParams,
}: {
  rows: MatrixRow[];
  columns: MetricColumn[];
  varyingParams: Record<string, string[]>;
  projectId: string;
  searchParams: URLSearchParams;
  setParams: (patch: Record<string, string | null>) => void;
}) {
  const setParam = (key: string, value: string | null) => setParams({ [key]: value });
  const router = useRouter();
  // Only metrics some experiment in the current view has (columns span every experiment).
  const metrics = useMemo(
    () =>
      chartMetrics(columns.filter((c) => rows.some((r) => r.metrics[c.key]?.mean != null))),
    [columns, rows],
  );
  const byKey = useMemo(() => new Map(metrics.map((m) => [m.key, m])), [metrics]);
  const valid = (key: string | null) => (key && byKey.has(key) ? key : null);

  const mode: ChartMode = searchParams.get(CHART_URL_KEYS.mode) === "tradeoff" ? "tradeoff" : "time";
  const colorBy = parseColorBy(searchParams.get(CHART_URL_KEYS.color), varyingParams);
  const defaults = defaultTradeoffAxes(metrics);
  const timeMetric =
    valid(searchParams.get(CHART_URL_KEYS.metric)) ??
    metrics.find((m) => m.kind === "evaluator")?.key ??
    metrics[0]?.key ??
    null;
  const xKey = valid(searchParams.get(CHART_URL_KEYS.x)) ?? defaults.x;
  const yKey = valid(searchParams.get(CHART_URL_KEYS.y)) ?? defaults.y;

  const timeData = useMemo(
    () => (timeMetric ? timeSeriesData(rows, timeMetric, colorBy) : null),
    [rows, timeMetric, colorBy],
  );
  const tradeoff = useMemo(() => {
    if (!xKey || !yKey) return null;
    const data = tradeoffData(rows, xKey, yKey, colorBy);
    const front = paretoFront(
      data.points,
      byKey.get(xKey)?.lowerIsBetter ?? false,
      byKey.get(yKey)?.lowerIsBetter ?? false,
    );
    return { data, front };
  }, [rows, xKey, yKey, colorBy, byKey]);

  if (metrics.length === 0 || rows.length < 2) return null;

  const open = (id: string) => router.push(experimentHref(projectId, id));
  const colorOptions = colorByOptions(varyingParams);
  const shown = mode === "time" ? timeData : tradeoff?.data;
  const missing = shown ? rows.length - shown.points.length : rows.length;

  return (
    <section
      aria-label="Experiment charts"
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Chart type" className="inline-flex rounded-md border border-border p-0.5">
          {(
            [
              ["time", "Over time"],
              ["tradeoff", "Trade-off"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => setParam(CHART_URL_KEYS.mode, value === "time" ? null : value)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium",
                mode === value
                  ? "bg-surface-2 text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        {mode === "time" ? (
          <MetricSelect
            label="Metric"
            value={timeMetric}
            metrics={metrics}
            onChange={(v) => setParam(CHART_URL_KEYS.metric, v)}
          />
        ) : (
          <>
            <MetricSelect
              label="Y"
              value={yKey}
              metrics={metrics}
              onChange={(v) => setParam(CHART_URL_KEYS.y, v)}
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 px-2"
              title="Swap axes"
              aria-label="Swap axes"
              onClick={() => setParams({ [CHART_URL_KEYS.x]: yKey, [CHART_URL_KEYS.y]: xKey })}
            >
              <ArrowLeftRight className="size-3.5" />
            </Button>
            <MetricSelect
              label="X"
              value={xKey}
              metrics={metrics}
              onChange={(v) => setParam(CHART_URL_KEYS.x, v)}
            />
          </>
        )}
        <ColorSelect
          value={colorBy}
          options={colorOptions}
          onChange={(v) => setParam(CHART_URL_KEYS.color, v === "none" ? null : v)}
        />
      </div>

      <p className="text-xs text-muted-foreground">
        {mode === "time"
          ? "Each point is an experiment at the time it ran. Pick any score or run metric (cost, latency, error rate…)."
          : "Each point is an experiment. The dashed line joins the best trade-offs: no other experiment is better on both axes (↓ = lower is better)."}
        {missing > 0 ? ` ${missing} experiment${missing === 1 ? "" : "s"} without these metrics not shown.` : ""}
      </p>

      {mode === "time" && timeData ? (
        timeData.points.length === 0 ? (
          <EmptyChart />
        ) : (
          <OverTimeChart data={timeData} metric={byKey.get(timeMetric!)} onOpen={open} />
        )
      ) : null}
      {mode === "tradeoff" ? (
        !tradeoff || tradeoff.data.points.length === 0 ? (
          <EmptyChart />
        ) : (
          <TradeoffChart
            data={tradeoff.data}
            front={tradeoff.front}
            xMetric={byKey.get(xKey!)}
            yMetric={byKey.get(yKey!)}
            onOpen={open}
          />
        )
      ) : null}
    </section>
  );
}

function EmptyChart() {
  return (
    <p className="py-10 text-center text-sm text-muted-foreground">
      No experiment in this view has these metrics.
    </p>
  );
}
