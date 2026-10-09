"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatTs } from "@/lib/format";
import type { LiveSeriesBucket } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { shouldShowLiveChart } from "./map-overview";

const ChartInner = dynamic(() => import("./live-quality-chart-inner").then((m) => m.LiveQualityChartInner), {
  ssr: false,
  loading: () => (
    <div
      className="h-[220px] animate-pulse rounded-md bg-surface-2"
      aria-hidden
    />
  ),
});

export function LiveQualityChart({
  projectId,
  series,
  referenceThreshold,
  onWidenRange,
}: {
  projectId: string;
  series: LiveSeriesBucket[];
  referenceThreshold: number | null;
  onWidenRange?: () => void;
}) {
  const [tableOpen, setTableOpen] = useState(false);
  const showChart = shouldShowLiveChart(series);

  return (
    <section
      id="live-quality-chart"
      aria-label="Live quality over time"
      className="flex flex-col gap-2 rounded-md border border-border bg-surface p-3"
    >
      <h2 className="text-sm font-semibold text-foreground">Live quality</h2>
      {!showChart ? (
        <div className="flex flex-col items-start gap-2 py-6 text-sm text-muted-foreground">
          <p>Not enough points in range.</p>
          {onWidenRange ? (
            <Button type="button" variant="outline" size="sm" onClick={onWidenRange}>
              Widen range
            </Button>
          ) : null}
        </div>
      ) : (
        <>
          <ChartInner series={series} referenceThreshold={referenceThreshold} />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 self-start px-2 text-xs"
            onClick={() => setTableOpen((o) => !o)}
            aria-expanded={tableOpen}
          >
            {tableOpen ? "Hide data" : "View data"}
          </Button>
          {tableOpen ? (
            <div className="max-h-48 overflow-auto rounded border border-border">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-surface-2">
                  <tr>
                    <th className="px-2 py-1 font-medium">Bucket</th>
                    <th className="px-2 py-1 font-medium">n</th>
                    <th className="px-2 py-1 font-medium">Mean score</th>
                    <th className="px-2 py-1 font-medium">Fail rate</th>
                  </tr>
                </thead>
                <tbody>
                  {series.map((row) => (
                    <tr key={row.bucket_start} className="border-t border-border">
                      <td className="px-2 py-1 font-mono tabular-nums">
                        {formatTs(row.bucket_start)}
                      </td>
                      <td className="px-2 py-1 font-mono tabular-nums">{row.n}</td>
                      <td className="px-2 py-1 font-mono tabular-nums">
                        {row.mean_score != null ? row.mean_score.toFixed(2) : "—"}
                      </td>
                      <td className="px-2 py-1 font-mono tabular-nums">
                        {row.fail_rate != null
                          ? `${(row.fail_rate * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
      <Link
        href={withProjectQuery("/live-runs", projectId)}
        className={cn("text-xs text-primary hover:underline")}
      >
        Open live runs
      </Link>
    </section>
  );
}
