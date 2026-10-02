"use client";

import { useMemo } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { cn } from "@/lib/cn";
import type { MetricComparison } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import { sortMetricsForDisplay } from "./sort-metrics";

export const METRIC_STATUS_STYLES: Record<string, string> = {
  regression: "bg-status-fail-bg text-status-fail",
  improved: "bg-status-ok-bg text-status-ok",
  unchanged: "bg-status-unset-bg text-status-unset",
  unavailable: "bg-status-warn-bg text-status-warn",
};

function formatMetricValue(value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 0 && Math.abs(value) <= 1) {
    return value.toFixed(4);
  }
  return value.toFixed(2);
}

function formatDelta(value: number | null): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
}

export function CompareStatusCell({ status }: { status: string }) {
  const style =
    METRIC_STATUS_STYLES[status] ??
    "bg-status-unset-bg text-status-unset";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium capitalize",
        style,
      )}
    >
      {status}
    </span>
  );
}

type CompareTableProps = {
  metrics: MetricComparison[];
};

export function CompareTable({ metrics }: CompareTableProps) {
  const rows = useMemo(() => sortMetricsForDisplay(metrics), [metrics]);

  const columns: DataTableColumn<MetricComparison>[] = useMemo(
    () => [
      {
        id: "evaluator",
        header: "Evaluator",
        cell: (row) => (
          <span className="text-sm text-foreground">
            {row.evaluator_name?.trim() ||
              truncateId(row.evaluator_id, 10)}
          </span>
        ),
      },
      {
        id: "metric",
        header: "Metric",
        cell: (row) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.metric}
          </span>
        ),
      },
      {
        id: "candidate",
        header: "Candidate",
        headerClassName: "w-[100px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatMetricValue(row.candidate),
      },
      {
        id: "baseline",
        header: "Baseline",
        headerClassName: "w-[100px] text-right",
        className: "text-right font-mono tabular-nums text-sm text-muted-foreground",
        cell: (row) => formatMetricValue(row.baseline),
      },
      {
        id: "delta",
        header: "Delta",
        headerClassName: "w-[100px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatDelta(row.delta),
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[120px]",
        cell: (row) => <CompareStatusCell status={row.status} />,
      },
    ],
    [],
  );

  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No comparable metrics for this pair of experiments.
      </p>
    );
  }

  return (
    <DataTable
      rows={rows}
      columns={columns}
      getRowKey={(row) => `${row.evaluator_id}-${row.metric}`}
      selectedIndex={0}
      onSelectedIndexChange={() => {}}
      onRowActivate={() => {}}
      aria-label="Experiment comparison metrics"
    />
  );
}
