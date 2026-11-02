"use client";

import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatBucketTick } from "@/lib/format";
import {
  formatChartValue,
  type ChartData,
  type ChartMetric,
  type ChartPoint,
} from "./experiment-charts";

// Five distinct hues; series past the fifth reuse them with a different marker.
const PALETTE = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
];
const SHAPES = ["circle", "diamond", "triangle", "square", "star"] as const;

const LEGEND_STYLE = { fontSize: 11, paddingBottom: 8 };

function formatDateTime(ms: number): string {
  return new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function PointTooltip({
  active,
  payload,
  xLabel,
  yLabel,
  formatX,
  formatY,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
  xLabel: string;
  yLabel: string;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
}) {
  const point = active ? (payload?.[0]?.payload as ChartPoint | undefined) : undefined;
  if (!point) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 font-medium text-foreground">{point.name}</div>
      {point.series !== "Experiments" ? (
        <div className="text-muted-foreground">{point.series}</div>
      ) : null}
      <div className="tabular-nums text-foreground">
        {yLabel}: {formatY(point.y)}
      </div>
      <div className="tabular-nums text-muted-foreground">
        {xLabel}: {formatX(point.x)}
      </div>
      <div className="mt-1 text-muted-foreground">Click to open</div>
    </div>
  );
}

function bySeries(data: ChartData): [string, ChartPoint[]][] {
  return data.series.map((name) => [name, data.points.filter((p) => p.series === name)]);
}

function yDomain(metric: ChartMetric | undefined): [number, number] | ["auto", "auto"] {
  return metric?.kind === "evaluator" ? [0, 1] : ["auto", "auto"];
}

type ChartProps = {
  data: ChartData;
  onOpen: (experimentId: string) => void;
};

function openFrom(onOpen: (id: string) => void) {
  return (item: { payload?: unknown }) => {
    const point = item?.payload as ChartPoint | undefined;
    if (point?.id) onOpen(point.id);
  };
}

/** Each experiment at its creation time; one line per series. */
export function MetricOverTimeChartInner({
  data,
  metric,
  onOpen,
}: ChartProps & { metric: ChartMetric | undefined }) {
  const formatY = (v: number) => formatChartValue(metric, v);
  const series = bySeries(data);
  const spanMs = data.points.length ? data.points.at(-1)!.x - data.points[0].x : 0;
  // Experiments of one day differ by the hour: show times, not the same date on every tick.
  const formatTick = (ms: number) => formatBucketTick(new Date(ms).toISOString(), spanMs);
  return (
    <ResponsiveContainer width="100%" height={280}>
      <ScatterChart margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          type="number"
          dataKey="x"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={formatTick}
          minTickGap={24}
          tick={{ fontSize: 10 }}
          name="Created"
        />
        <YAxis
          type="number"
          dataKey="y"
          domain={yDomain(metric)}
          tickFormatter={formatY}
          tick={{ fontSize: 10 }}
          width={56}
          name={metric?.label}
        />
        <Tooltip
          cursor={{ strokeDasharray: "3 3" }}
          content={(props) => (
            <PointTooltip
              active={props.active}
              payload={props.payload}
              xLabel="Created"
              yLabel={metric?.label ?? ""}
              formatX={formatDateTime}
              formatY={formatY}
            />
          )}
        />
        {series.length > 1 ? (
          <Legend verticalAlign="top" align="right" wrapperStyle={LEGEND_STYLE} />
        ) : null}
        {series.map(([name, points], i) => (
          <Scatter
            key={name}
            name={name}
            data={points}
            fill={PALETTE[i % PALETTE.length]}
            stroke={PALETTE[i % PALETTE.length]}
            shape={SHAPES[Math.floor(i / PALETTE.length) % SHAPES.length]}
            line
            lineType="joint"
            isAnimationActive={false}
            onClick={openFrom(onOpen)}
            className="cursor-pointer"
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

/** Two metrics against each other; the dashed line joins the best trade-offs. */
export function TradeoffChartInner({
  data,
  front,
  xMetric,
  yMetric,
  onOpen,
}: ChartProps & {
  front: ChartPoint[];
  xMetric: ChartMetric | undefined;
  yMetric: ChartMetric | undefined;
}) {
  const formatX = (v: number) => formatChartValue(xMetric, v);
  const formatY = (v: number) => formatChartValue(yMetric, v);
  const series = bySeries(data);
  return (
    <ResponsiveContainer width="100%" height={320}>
      <ScatterChart margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          type="number"
          dataKey="x"
          domain={yDomain(xMetric)}
          tickFormatter={formatX}
          tick={{ fontSize: 10 }}
          name={xMetric?.label}
        />
        <YAxis
          type="number"
          dataKey="y"
          domain={yDomain(yMetric)}
          tickFormatter={formatY}
          tick={{ fontSize: 10 }}
          width={56}
          name={yMetric?.label}
        />
        <Tooltip
          cursor={{ strokeDasharray: "3 3" }}
          content={(props) => (
            <PointTooltip
              active={props.active}
              payload={props.payload}
              xLabel={xMetric?.label ?? ""}
              yLabel={yMetric?.label ?? ""}
              formatX={formatX}
              formatY={formatY}
            />
          )}
        />
        {series.length > 1 || front.length > 1 ? (
          <Legend verticalAlign="top" align="right" wrapperStyle={LEGEND_STYLE} />
        ) : null}
        {front.length > 1 ? (
          <Scatter
            name="Best trade-offs"
            data={front}
            fill="hsl(var(--muted-foreground))"
            stroke="hsl(var(--muted-foreground))"
            line={{
              stroke: "hsl(var(--muted-foreground))",
              strokeDasharray: "5 4",
              strokeWidth: 1.5,
            }}
            lineType="joint"
            shape={() => <g />}
            legendType="plainline"
            isAnimationActive={false}
          />
        ) : null}
        {series.map(([name, points], i) => (
          <Scatter
            key={name}
            name={name}
            data={points}
            fill={PALETTE[i % PALETTE.length]}
            shape={SHAPES[Math.floor(i / PALETTE.length) % SHAPES.length]}
            isAnimationActive={false}
            onClick={openFrom(onOpen)}
            className="cursor-pointer"
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}
