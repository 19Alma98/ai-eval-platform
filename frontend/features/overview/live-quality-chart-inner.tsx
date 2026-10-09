"use client";

import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { LiveSeriesBucket } from "@/lib/api/types";
import { formatTs } from "@/lib/format";

type ChartRow = {
  bucket: string;
  mean_score: number | null;
  fail_rate: number | null;
  n: number;
};

export function LiveQualityChartInner({
  series,
  referenceThreshold,
}: {
  series: LiveSeriesBucket[];
  referenceThreshold: number | null;
}) {
  const data = useMemo<ChartRow[]>(
    () =>
      series.map((b) => ({
        bucket: b.bucket_start,
        mean_score: b.mean_score,
        fail_rate: b.fail_rate != null ? b.fail_rate * 100 : null,
        n: b.n,
      })),
    [series],
  );

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          dataKey="bucket"
          tickFormatter={(v) => formatTs(String(v))}
          tick={{ fontSize: 10 }}
          interval="preserveStartEnd"
        />
        <YAxis
          yAxisId="score"
          domain={[0, 1]}
          tick={{ fontSize: 10 }}
          width={32}
        />
        <YAxis
          yAxisId="rate"
          orientation="right"
          domain={[0, 100]}
          tick={{ fontSize: 10 }}
          width={36}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          labelFormatter={(label) => formatTs(String(label))}
          formatter={(value, name) => {
            const n = typeof value === "number" ? value : null;
            const label = String(name ?? "");
            if (n == null) return ["—", label];
            if (label === "Fail rate") return [`${n.toFixed(1)}%`, label];
            return [n.toFixed(2), label];
          }}
        />
        {referenceThreshold != null ? (
          <ReferenceLine
            yAxisId="score"
            y={referenceThreshold}
            stroke="hsl(var(--status-warn))"
            strokeDasharray="4 4"
            label={{ value: "Threshold", position: "insideTopRight", fontSize: 10 }}
          />
        ) : null}
        <Area
          yAxisId="score"
          type="monotone"
          dataKey="mean_score"
          name="Mean score"
          fill="hsl(var(--primary) / 0.15)"
          stroke="hsl(var(--primary))"
          connectNulls
        />
        <Line
          yAxisId="rate"
          type="monotone"
          dataKey="fail_rate"
          name="Fail rate"
          stroke="hsl(var(--status-fail))"
          strokeDasharray="4 4"
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
