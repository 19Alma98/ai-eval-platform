"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MetricColumn } from "./experiment-matrix";

const PALETTE = [
  "hsl(var(--primary))",
  "hsl(var(--status-ok))",
  "hsl(var(--status-warn))",
  "hsl(var(--status-fail))",
  "hsl(var(--kind-retriever))",
  "hsl(var(--kind-tool))",
];

export function MetricTrendChartInner({
  data,
  columns,
}: {
  data: Array<Record<string, number | string | null>>;
  columns: MetricColumn[];
}) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
        <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} width={32} />
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          formatter={(value, name) => [
            typeof value === "number" ? value.toFixed(2) : "—",
            String(name),
          ]}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {columns.map((col, i) => (
          <Line
            key={col.key}
            type="monotone"
            dataKey={col.key}
            name={col.label}
            stroke={PALETTE[i % PALETTE.length]}
            dot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
