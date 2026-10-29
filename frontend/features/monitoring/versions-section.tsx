"use client";

import { cn } from "@/lib/cn";
import { formatDurationMs, formatPercent } from "@/lib/format";
import type { VersionSummary } from "@/lib/api/types";
import { metricLabel } from "@/lib/metrics-catalog";
import { versionFailRate, versionMetricColumns, worstIndex } from "./version-table";

/**
 * Production health per release side by side: after a deploy, the new version's error
 * rate, latency, cost and failing answers next to the previous one.
 */
export function VersionsSection({
  rows,
  onSelect,
}: {
  rows: VersionSummary[];
  onSelect: (version: string) => void;
}) {
  if (rows.length === 0) return null;
  const metrics = versionMetricColumns(rows);
  const worst = {
    error: worstIndex(rows.map((r) => r.error_rate)),
    p90: worstIndex(rows.map((r) => r.latency.p90_ms)),
    cost: worstIndex(rows.map((r) => r.cost_per_trace_usd)),
    metrics: metrics.map((m) => worstIndex(rows.map((r) => versionFailRate(r, m)))),
  };
  const cell = "px-3 py-2 text-right tabular-nums";
  const bad = "font-semibold text-status-fail";

  return (
    <section aria-labelledby="versions-title" className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5">
        <h2 id="versions-title" className="text-sm font-semibold text-foreground">
          By version
        </h2>
        <p className="text-xs text-muted-foreground">
          Releases in this range (<code>service.version</code>, set with{" "}
          <code>opengrade.init(version=…)</code>), most traffic first. The worst value per
          column is red. Click a version to filter the page.
        </p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full text-sm">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Version</th>
              <th className="px-3 py-2 text-right font-medium">Traces</th>
              <th className="px-3 py-2 text-right font-medium">Errors</th>
              <th className="px-3 py-2 text-right font-medium">Latency p90</th>
              <th className="px-3 py-2 text-right font-medium">Cost / trace</th>
              {metrics.map((m) => (
                <th key={m.key} className="px-3 py-2 text-right font-medium">
                  {m.source === "judge" ? metricLabel(m.name) : m.name} failing
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.version ?? "none"}
                className="cursor-pointer border-b border-border last:border-0 hover:bg-row-hover"
                onClick={() => row.version && onSelect(row.version)}
              >
                <td className="px-3 py-2 font-medium text-foreground">{row.version ?? "—"}</td>
                <td className={cell}>
                  {row.n_traces.toLocaleString()}
                  {row.traces_truncated ? "+" : ""}
                </td>
                <td className={cn(cell, worst.error === i && bad)}>
                  {formatPercent(row.error_rate)}
                </td>
                <td className={cn(cell, worst.p90 === i && bad)}>
                  {row.latency.p90_ms != null ? formatDurationMs(row.latency.p90_ms) : "—"}
                </td>
                <td className={cn(cell, worst.cost === i && bad)}>
                  {row.cost_per_trace_usd != null ? `$${row.cost_per_trace_usd.toFixed(5)}` : "—"}
                </td>
                {metrics.map((m, j) => (
                  <td key={m.key} className={cn(cell, worst.metrics[j] === i && bad)}>
                    {formatPercent(versionFailRate(row, m))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
