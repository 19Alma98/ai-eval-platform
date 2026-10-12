"use client";

import { useMemo } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { cn } from "@/lib/cn";
import type { MetricComparison } from "@/lib/api/types";
import { formatStatusLabel } from "@/components/status-badge";
import { formatDeltaPoints, formatPercent, formatScore } from "@/lib/format";
import { metricInfo } from "@/lib/metrics-catalog";
import {
  groupMetricsByEvaluator,
  type EvaluatorCompareRow,
} from "./group-metrics-by-evaluator";

export const METRIC_STATUS_STYLES: Record<string, string> = {
  regression: "bg-status-fail-bg text-status-fail",
  improved: "bg-status-ok-bg text-status-ok",
  unchanged: "bg-status-unset-bg text-status-unset",
  unavailable: "bg-status-warn-bg text-status-warn",
  config_mismatch: "bg-status-warn-bg text-status-warn",
  insufficient_n: "bg-status-warn-bg text-status-warn",
};

const COMPARE_STATUS_LABELS: Record<string, string> = {
  regression: "Worse",
  improved: "Better",
  unchanged: "No real change",
  unavailable: "Not scored",
  config_mismatch: "Not comparable",
  insufficient_n: "Too few answers",
};

const COMPARE_STATUS_HINTS: Record<string, string> = {
  regression: "The candidate scores significantly lower than the baseline.",
  improved: "The candidate scores significantly higher than the baseline.",
  unchanged: "The difference is within normal variation.",
  unavailable: "One of the two experiments was not scored with this metric.",
  config_mismatch:
    "The two experiments were scored with different settings for this metric, so scores can't be compared.",
  insufficient_n: "Too few answers to tell a real change from noise.",
};

export function CompareStatusCell({ status }: { status: string }) {
  const style =
    METRIC_STATUS_STYLES[status.toLowerCase()] ??
    "bg-status-unset-bg text-status-unset";
  return (
    <span
      title={COMPARE_STATUS_HINTS[status.toLowerCase()]}
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
        style,
      )}
    >
      {COMPARE_STATUS_LABELS[status.toLowerCase()] ?? formatStatusLabel(status)}
    </span>
  );
}

type CompareTableProps = {
  metrics: MetricComparison[];
  selectedEvaluatorId: string | null;
  onSelectEvaluator: (evaluatorId: string) => void;
};

export function CompareTable({
  metrics,
  selectedEvaluatorId,
  onSelectEvaluator,
}: CompareTableProps) {
  const rows = useMemo(() => groupMetricsByEvaluator(metrics), [metrics]);

  const columns: DataTableColumn<EvaluatorCompareRow>[] = useMemo(
    () => [
      {
        id: "metric",
        header: "Metric",
        cell: (row) => {
          const info = metricInfo(row.evaluator_name);
          return (
            <span className="text-sm font-medium text-foreground" title={info.description}>
              {info.label}
            </span>
          );
        },
      },
      {
        id: "baseline",
        header: "Baseline passed",
        headerClassName: "w-[140px] text-right",
        className: "text-right tabular-nums text-sm text-muted-foreground",
        cell: (row) => formatPercent(row.baseline_pass_rate),
      },
      {
        id: "candidate",
        header: "Candidate passed",
        headerClassName: "w-[140px] text-right",
        className: "text-right tabular-nums text-sm font-medium",
        cell: (row) => formatPercent(row.candidate_pass_rate),
      },
      {
        id: "change",
        header: "Change",
        headerClassName: "w-[110px] text-right",
        className: "text-right tabular-nums text-sm",
        cell: (row) => {
          const delta =
            row.candidate_pass_rate != null && row.baseline_pass_rate != null
              ? row.candidate_pass_rate - row.baseline_pass_rate
              : null;
          return (
            <span
              className={cn(
                delta != null && delta < -0.0001 && "text-status-fail",
                delta != null && delta > 0.0001 && "text-status-ok",
              )}
            >
              {formatDeltaPoints(delta)}
            </span>
          );
        },
      },
      {
        id: "score",
        header: "Avg. score",
        headerClassName: "w-[130px] text-right",
        className: "text-right tabular-nums text-xs text-muted-foreground",
        cell: (row) =>
          `${formatScore(row.baseline_mean)} → ${formatScore(row.candidate_mean)}`,
      },
      {
        id: "status",
        header: "Verdict",
        headerClassName: "w-[140px]",
        cell: (row) => <CompareStatusCell status={row.status} />,
      },
    ],
    [],
  );

  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        These two experiments have no metrics in common yet. Score both with the
        same metrics to compare them.
      </p>
    );
  }

  const selectedIndex = Math.max(
    0,
    rows.findIndex((r) => r.evaluator_id === selectedEvaluatorId),
  );

  return (
    <DataTable
      rows={rows}
      columns={columns}
      getRowKey={(row) => row.evaluator_id}
      selectedIndex={selectedIndex}
      onSelectedIndexChange={(i) => {
        const row = rows[i];
        if (row) onSelectEvaluator(row.evaluator_id);
      }}
      onRowActivate={(row) => onSelectEvaluator(row.evaluator_id)}
      selectionMode="persistent"
      aria-label="Metrics compared"
    />
  );
}
