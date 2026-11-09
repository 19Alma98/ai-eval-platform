"use client";

import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MetricMonitor, TrafficBucket } from "@/lib/api/types";
import { formatBucketTick, formatDurationMs, formatTs, parseTimestamp } from "@/lib/format";

const AXIS_TICK = { fontSize: 10 };
const PREV_STROKE = "hsl(var(--muted-foreground))";

/** Per-bucket costs are often fractions of a cent: keep two significant digits. */
function formatUsd(value: number): string {
  if (value === 0) return "$0";
  return value >= 1 ? `$${value.toFixed(2)}` : `$${Number(value.toPrecision(2))}`;
}
const TOOLTIP_STYLE = { fontSize: 12 };

export type ChartBucketClick = {
  bucketStart: string;
  /** Which series was clicked, when known (e.g. "errors"). */
  series?: string;
};

type ChartChrome = {
  timeZone?: string;
  onBucketClick?: (click: ChartBucketClick) => void;
};

function timeAxis(data: { bucket: string }[], timeZone?: string) {
  const first = data[0]?.bucket;
  const last = data.at(-1)?.bucket;
  const spanMs = first && last ? parseTimestamp(last).getTime() - parseTimestamp(first).getTime() : 0;
  return (
    <XAxis
      dataKey="bucket"
      tickFormatter={(v) => formatBucketTick(String(v), spanMs, undefined, timeZone)}
      tick={AXIS_TICK}
      interval="preserveStartEnd"
      minTickGap={16}
    />
  );
}

function labelTs(label: unknown, timeZone?: string) {
  return formatTs(String(label), undefined, timeZone);
}

/**
 * Lines are drawn without dots, so a series with a single non-empty bucket (all
 * traffic in one bucket) would render nothing: show a dot in that case.
 */
function dotWhenSparse(data: Record<string, unknown>[], key: string) {
  const points = data.filter((row) => typeof row[key] === "number").length;
  return points <= 1 ? { r: 3 } : false;
}

function clickPayload(state: unknown): ChartBucketClick | null {
  if (!state || typeof state !== "object") return null;
  const activeLabel = (state as { activeLabel?: unknown }).activeLabel;
  if (typeof activeLabel !== "string" || !activeLabel) return null;
  const payload = (state as { activePayload?: { dataKey?: unknown }[] }).activePayload?.[0];
  const series = typeof payload?.dataKey === "string" ? payload.dataKey : undefined;
  return { bucketStart: activeLabel, series };
}

export function LatencyChartInner({
  traffic,
  previous,
  timeZone,
  onBucketClick,
}: {
  traffic: TrafficBucket[];
  previous?: TrafficBucket[] | null;
} & ChartChrome) {
  const data = traffic.map((b, i) => ({
    bucket: b.bucket_start,
    p50: b.latency.p50_ms,
    p90: b.latency.p90_ms,
    p99: b.latency.p99_ms,
    p50_prev: previous?.[i]?.latency.p50_ms ?? null,
    p90_prev: previous?.[i]?.latency.p90_ms ?? null,
    p99_prev: previous?.[i]?.latency.p99_ms ?? null,
  }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart
        data={data}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        onClick={(state) => {
          const click = clickPayload(state);
          if (click) onBucketClick?.(click);
        }}
        style={onBucketClick ? { cursor: "pointer" } : undefined}
      >
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis(data, timeZone)}
        <YAxis tick={AXIS_TICK} width={48} tickFormatter={(v) => formatDurationMs(Number(v))} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(label) => labelTs(label, timeZone)}
          formatter={(value, name) => [
            typeof value === "number" ? formatDurationMs(value) : "—",
            String(name),
          ]}
        />
        <Line type="monotone" dataKey="p50" name="p50" stroke="hsl(var(--primary))" dot={dotWhenSparse(data, "p50")} connectNulls />
        <Line type="monotone" dataKey="p90" name="p90" stroke="hsl(var(--status-warn))" dot={dotWhenSparse(data, "p90")} connectNulls />
        <Line
          type="monotone"
          dataKey="p99"
          name="p99"
          stroke="hsl(var(--status-fail))"
          strokeDasharray="4 4"
          dot={dotWhenSparse(data, "p99")}
          connectNulls
        />
        {previous ? (
          <>
            <Line type="monotone" dataKey="p50_prev" name="p50 prev" stroke={PREV_STROKE} strokeDasharray="3 3" dot={false} connectNulls />
            <Line type="monotone" dataKey="p90_prev" name="p90 prev" stroke={PREV_STROKE} strokeDasharray="3 3" dot={false} connectNulls />
            <Line type="monotone" dataKey="p99_prev" name="p99 prev" stroke={PREV_STROKE} strokeDasharray="3 3" dot={false} connectNulls />
          </>
        ) : null}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function TrafficChartInner({
  traffic,
  previous,
  timeZone,
  onBucketClick,
}: {
  traffic: TrafficBucket[];
  previous?: TrafficBucket[] | null;
} & ChartChrome) {
  const data = traffic.map((b, i) => ({
    bucket: b.bucket_start,
    ok: b.n_traces - b.n_errors,
    errors: b.n_errors,
    ok_prev: previous ? (previous[i]?.n_traces ?? 0) - (previous[i]?.n_errors ?? 0) : null,
    errors_prev: previous?.[i]?.n_errors ?? null,
  }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart
        data={data}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        onClick={(state) => {
          const click = clickPayload(state);
          if (click) onBucketClick?.(click);
        }}
        style={onBucketClick ? { cursor: "pointer" } : undefined}
      >
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis(data, timeZone)}
        <YAxis tick={AXIS_TICK} width={32} allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(label) => labelTs(label, timeZone)} />
        <Bar dataKey="ok" name="OK" stackId="t" fill="hsl(var(--primary) / 0.6)" />
        <Bar dataKey="errors" name="Errors" stackId="t" fill="hsl(var(--status-fail))" />
        {previous ? (
          <>
            <Bar dataKey="ok_prev" name="OK prev" stackId="p" fill="hsl(var(--muted-foreground) / 0.25)" />
            <Bar dataKey="errors_prev" name="Errors prev" stackId="p" fill="hsl(var(--muted-foreground) / 0.45)" />
          </>
        ) : null}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function UsageChartInner({
  traffic,
  previous,
  timeZone,
  onBucketClick,
}: {
  traffic: TrafficBucket[];
  previous?: TrafficBucket[] | null;
} & ChartChrome) {
  const data = traffic.map((b, i) => ({
    bucket: b.bucket_start,
    tokens: b.total_tokens,
    cost: b.cost_usd,
    tokens_prev: previous?.[i]?.total_tokens ?? null,
    cost_prev: previous?.[i]?.cost_usd ?? null,
  }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart
        data={data}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        onClick={(state) => {
          const click = clickPayload(state);
          if (click) onBucketClick?.(click);
        }}
        style={onBucketClick ? { cursor: "pointer" } : undefined}
      >
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis(data, timeZone)}
        <YAxis yAxisId="tokens" tick={AXIS_TICK} width={48} />
        <YAxis
          yAxisId="cost"
          orientation="right"
          tick={AXIS_TICK}
          width={48}
          tickFormatter={(v) => formatUsd(Number(v))}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(label) => labelTs(label, timeZone)}
          formatter={(value, name) => {
            const n = typeof value === "number" ? value : 0;
            return String(name).includes("Cost")
              ? [`$${n.toFixed(4)}`, String(name)]
              : [Math.round(n).toLocaleString(), String(name)];
          }}
        />
        <Bar yAxisId="tokens" dataKey="tokens" name="Tokens" fill="hsl(var(--primary) / 0.5)" />
        <Line yAxisId="cost" type="monotone" dataKey="cost" name="Cost" stroke="hsl(var(--status-warn))" dot={dotWhenSparse(data, "cost")} />
        {previous ? (
          <>
            <Bar yAxisId="tokens" dataKey="tokens_prev" name="Tokens prev" fill="hsl(var(--muted-foreground) / 0.25)" />
            <Line
              yAxisId="cost"
              type="monotone"
              dataKey="cost_prev"
              name="Cost prev"
              stroke={PREV_STROKE}
              strokeDasharray="3 3"
              dot={false}
            />
          </>
        ) : null}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function MetricSeriesChartInner({
  metric,
  alarmLimit,
  previous,
  timeZone,
  onBucketClick,
}: {
  metric: MetricMonitor;
  alarmLimit: number;
  previous?: MetricMonitor | null;
} & ChartChrome) {
  const data = metric.series.map((b, i) => ({
    bucket: b.bucket_start,
    mean: b.mean,
    fail_rate: b.fail_rate != null ? b.fail_rate * 100 : null,
    mean_prev: previous?.series[i]?.mean ?? null,
    fail_rate_prev:
      previous?.series[i]?.fail_rate != null ? previous.series[i]!.fail_rate! * 100 : null,
  }));
  const unitScale = metric.histogram_edges.length === 0 || metric.histogram_edges.at(-1)! <= 1;
  return (
    <ResponsiveContainer width="100%" height={160}>
      <ComposedChart
        data={data}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        onClick={(state) => {
          const click = clickPayload(state);
          if (click) onBucketClick?.(click);
        }}
        style={onBucketClick ? { cursor: "pointer" } : undefined}
      >
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis(data, timeZone)}
        <YAxis yAxisId="score" domain={unitScale ? [0, 1] : ["auto", "auto"]} tick={AXIS_TICK} width={32} />
        <YAxis
          yAxisId="rate"
          orientation="right"
          domain={[0, 100]}
          tick={AXIS_TICK}
          width={36}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(label) => labelTs(label, timeZone)}
          formatter={(value, name) => {
            const n = typeof value === "number" ? value : null;
            if (n == null) return ["—", String(name)];
            return String(name).includes("Fail")
              ? [`${n.toFixed(1)}%`, String(name)]
              : [n.toFixed(2), String(name)];
          }}
        />
        {metric.threshold != null ? (
          <ReferenceLine
            yAxisId="score"
            y={metric.threshold}
            stroke="hsl(var(--status-warn))"
            strokeDasharray="4 4"
            label={{ value: "Pass threshold", position: "insideTopLeft", fontSize: 10 }}
          />
        ) : null}
        <ReferenceLine
          yAxisId="rate"
          y={alarmLimit * 100}
          stroke="hsl(var(--status-fail))"
          strokeDasharray="2 4"
          label={{ value: "Alarm", position: "insideTopRight", fontSize: 10 }}
        />
        <Area
          yAxisId="score"
          type="monotone"
          dataKey="mean"
          name="Mean"
          fill="hsl(var(--primary) / 0.15)"
          stroke="hsl(var(--primary))"
          dot={{ r: 2 }}
          connectNulls
        />
        <Line
          yAxisId="rate"
          type="monotone"
          dataKey="fail_rate"
          name="Fail rate"
          stroke="hsl(var(--status-fail))"
          dot={{ r: 2 }}
          connectNulls
        />
        {previous ? (
          <>
            <Line
              yAxisId="score"
              type="monotone"
              dataKey="mean_prev"
              name="Mean prev"
              stroke={PREV_STROKE}
              strokeDasharray="3 3"
              dot={false}
              connectNulls
            />
            <Line
              yAxisId="rate"
              type="monotone"
              dataKey="fail_rate_prev"
              name="Fail rate prev"
              stroke={PREV_STROKE}
              strokeDasharray="3 3"
              dot={false}
              connectNulls
            />
          </>
        ) : null}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function HistogramChartInner({ metric }: { metric: MetricMonitor }) {
  const edges = metric.histogram_edges;
  const data = metric.histogram_counts.map((count, i) => ({
    bin: `${edges[i].toFixed(1)}–${edges[i + 1].toFixed(1)}`,
    start: edges[i],
    count,
  }));
  const thresholdBin =
    metric.threshold != null
      ? data.find((d, i) => metric.threshold! >= edges[i] && metric.threshold! <= edges[i + 1])?.bin
      : undefined;
  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="bin" tick={AXIS_TICK} interval={1} />
        <YAxis tick={AXIS_TICK} width={32} allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        {thresholdBin ? (
          <ReferenceLine
            x={thresholdBin}
            stroke="hsl(var(--status-warn))"
            strokeDasharray="4 4"
            label={{ value: "Threshold", position: "insideTopRight", fontSize: 10 }}
          />
        ) : null}
        <Bar dataKey="count" name="Answers" fill="hsl(var(--primary) / 0.6)" />
      </BarChart>
    </ResponsiveContainer>
  );
}
