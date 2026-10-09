"use client";

import { useRouter } from "next/navigation";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { withProjectQuery } from "@/lib/project-href";
import type { PassRateBar } from "./map-overview";

const MAX_BARS = 6;

export function CompareBarsInner({
  bars,
  projectId,
  compareHref,
  moreCount,
  onMoreClick,
}: {
  bars: PassRateBar[];
  projectId: string;
  compareHref: string | null;
  moreCount: number;
  onMoreClick?: () => void;
}) {
  const router = useRouter();
  const shown = bars.slice(0, MAX_BARS);
  const data = shown.map((b) => ({
    name: b.name,
    candidate: b.candidate != null ? b.candidate * 100 : null,
    baseline: b.baseline != null ? b.baseline * 100 : null,
    bar: b,
  }));

  function navigate(bar: PassRateBar) {
    if (bar.baselineExperimentId) {
      const path = `/experiments/${encodeURIComponent(bar.candidateExperimentId)}/compare?baseline=${encodeURIComponent(bar.baselineExperimentId)}`;
      router.push(withProjectQuery(path, projectId));
      return;
    }
    router.push(
      withProjectQuery(
        `/experiments/${encodeURIComponent(bar.candidateExperimentId)}`,
        projectId,
      ),
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <ResponsiveContainer width="100%" height={Math.max(160, shown.length * 36)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 8, left: 8, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fontSize: 10 }}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={100}
            tick={{ fontSize: 10 }}
          />
          <Tooltip
            formatter={(value, name) => {
              const n = typeof value === "number" ? value : null;
              const label = String(name ?? "");
              return n != null ? [`${n.toFixed(1)}%`, label] : ["—", label];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar
            dataKey="candidate"
            name="Candidate"
            fill="hsl(var(--primary))"
            radius={[0, 2, 2, 0]}
            cursor="pointer"
            onClick={(_data, index) => {
              const row = shown[index];
              if (row) navigate(row);
            }}
          />
          <Bar
            dataKey="baseline"
            name="Baseline"
            fill="hsl(var(--muted-foreground) / 0.45)"
            radius={[0, 2, 2, 0]}
            cursor="pointer"
            onClick={(_data, index) => {
              const row = shown[index];
              if (row) navigate(row);
            }}
          />
        </BarChart>
      </ResponsiveContainer>
      {moreCount > 0 && compareHref ? (
        <button
          type="button"
          className="text-left text-xs text-primary hover:underline"
          onClick={() => {
            if (onMoreClick) onMoreClick();
            else router.push(withProjectQuery(compareHref, projectId));
          }}
        >
          +{moreCount} more
        </button>
      ) : null}
    </div>
  );
}
