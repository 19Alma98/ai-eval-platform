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
import { formatDurationMs, formatTs } from "@/lib/format";

const AXIS_TICK = { fontSize: 10 };

/** Per-bucket costs are often fractions of a cent: keep two significant digits. */
function formatUsd(value: number): string {
  if (value === 0) return "$0";
  return value >= 1 ? `$${value.toFixed(2)}` : `$${Number(value.toPrecision(2))}`;
}
const TOOLTIP_STYLE = { fontSize: 12 };

function timeAxis() {
  return (
    <XAxis
      dataKey="bucket"
      tickFormatter={(v) =>
        new Date(String(v)).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      }
      tick={AXIS_TICK}
      interval="preserveStartEnd"
    />
  );
}

export function LatencyChartInner({ traffic }: { traffic: TrafficBucket[] }) {
  const data = traffic.map((b) => ({
    bucket: b.bucket_start,
    p50: b.latency.p50_ms,
    p90: b.latency.p90_ms,
    p99: b.latency.p99_ms,
  }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis()}
        <YAxis tick={AXIS_TICK} width={48} tickFormatter={(v) => formatDurationMs(Number(v))} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(label) => formatTs(String(label))}
          formatter={(value, name) => [
            typeof value === "number" ? formatDurationMs(value) : "—",
            String(name),
          ]}
        />
        <Line type="monotone" dataKey="p50" name="p50" stroke="hsl(var(--primary))" dot={false} connectNulls />
        <Line type="monotone" dataKey="p90" name="p90" stroke="hsl(var(--status-warn))" dot={false} connectNulls />
        <Line
          type="monotone"
          dataKey="p99"
          name="p99"
          stroke="hsl(var(--status-fail))"
          strokeDasharray="4 4"
          dot={false}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function TrafficChartInner({ traffic }: { traffic: TrafficBucket[] }) {
  const data = traffic.map((b) => ({
    bucket: b.bucket_start,
    ok: b.n_traces - b.n_errors,
    errors: b.n_errors,
  }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis()}
        <YAxis tick={AXIS_TICK} width={32} allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(label) => formatTs(String(label))} />
        <Bar dataKey="ok" name="OK" stackId="t" fill="hsl(var(--primary) / 0.6)" />
        <Bar dataKey="errors" name="Errors" stackId="t" fill="hsl(var(--status-fail))" />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function UsageChartInner({ traffic }: { traffic: TrafficBucket[] }) {
  const data = traffic.map((b) => ({
    bucket: b.bucket_start,
    tokens: b.total_tokens,
    cost: b.cost_usd,
  }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis()}
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
          labelFormatter={(label) => formatTs(String(label))}
          formatter={(value, name) => {
            const n = typeof value === "number" ? value : 0;
            return name === "Cost" ? [`$${n.toFixed(4)}`, "Cost"] : [Math.round(n).toLocaleString(), String(name)];
          }}
        />
        <Bar yAxisId="tokens" dataKey="tokens" name="Tokens" fill="hsl(var(--primary) / 0.5)" />
        <Line yAxisId="cost" type="monotone" dataKey="cost" name="Cost" stroke="hsl(var(--status-warn))" dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function MetricSeriesChartInner({
  metric,
  alarmLimit,
}: {
  metric: MetricMonitor;
  alarmLimit: number;
}) {
  const data = metric.series.map((b) => ({
    bucket: b.bucket_start,
    mean: b.mean,
    fail_rate: b.fail_rate != null ? b.fail_rate * 100 : null,
  }));
  const unitScale = metric.histogram_edges.length === 0 || metric.histogram_edges.at(-1)! <= 1;
  return (
    <ResponsiveContainer width="100%" height={160}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        {timeAxis()}
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
          labelFormatter={(label) => formatTs(String(label))}
          formatter={(value, name) => {
            const n = typeof value === "number" ? value : null;
            if (n == null) return ["—", String(name)];
            return name === "Fail rate" ? [`${n.toFixed(1)}%`, "Fail rate"] : [n.toFixed(2), String(name)];
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
