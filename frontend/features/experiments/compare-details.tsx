"use client";

import { useState } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { cn } from "@/lib/cn";
import type { ExperimentMetricComparison } from "@/lib/api/types";
import { deltaTone, isLowerBetter } from "./metric-direction";
import type { CompareOptionalColumn } from "./compare-url-state";
import { paramDiff } from "./experiment-matrix";

function formatMetricValue(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (Number.isInteger(value)) return String(value);
  const abs = Math.abs(value);
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 1) return value.toFixed(2);
  return value.toFixed(4);
}

function formatSignedDelta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const body = formatMetricValue(Math.abs(value));
  if (Math.abs(value) < 1e-9) return body;
  return value > 0 ? `+${body}` : `−${body}`;
}

type CompareDetailsProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  experimentMetrics: ExperimentMetricComparison[];
  candidateConfig: Record<string, unknown>;
  baselineConfig: Record<string, unknown>;
  visibleCols: Set<CompareOptionalColumn>;
  onVisibleColsChange: (cols: Set<CompareOptionalColumn>) => void;
};

export function CompareDetails({
  open,
  onOpenChange,
  experimentMetrics,
  candidateConfig,
  baselineConfig,
  visibleCols,
  onVisibleColsChange,
}: CompareDetailsProps) {
  const params = paramDiff(candidateConfig, baselineConfig);
  const [metricSelected, setMetricSelected] = useState(0);
  const [paramSelected, setParamSelected] = useState(0);

  function toggleCol(col: CompareOptionalColumn, checked: boolean) {
    const next = new Set(visibleCols);
    if (checked) next.add(col);
    else next.delete(col);
    onVisibleColsChange(next);
  }

  const metricColumns: DataTableColumn<ExperimentMetricComparison>[] = [
    {
      id: "key",
      header: "Logged metric",
      cell: (row) => (
        <span className="font-mono text-xs text-foreground">{row.key}</span>
      ),
    },
    {
      id: "baseline",
      header: "Baseline",
      headerClassName: "w-[120px] text-right",
      className: "text-right tabular-nums text-sm text-muted-foreground",
      cell: (row) => formatMetricValue(row.baseline),
    },
    {
      id: "candidate",
      header: "Candidate",
      headerClassName: "w-[120px] text-right",
      className: "text-right tabular-nums text-sm font-medium",
      cell: (row) => formatMetricValue(row.candidate),
    },
    {
      id: "delta",
      header: "Change",
      headerClassName: "w-[120px] text-right",
      className: "text-right tabular-nums text-sm",
      cell: (row) => {
        const tone = deltaTone(row.delta, isLowerBetter(row.key));
        return (
          <span
            className={cn(
              tone === "better" && "text-status-ok",
              tone === "worse" && "text-status-fail",
            )}
          >
            {formatSignedDelta(row.delta)}
          </span>
        );
      },
    },
  ];

  const paramColumns: DataTableColumn<{
    key: string;
    candidate: string | null;
    baseline: string | null;
  }>[] = [
    {
      id: "key",
      header: "Parameter",
      cell: (row) => (
        <span className="font-mono text-xs text-foreground">{row.key}</span>
      ),
    },
    {
      id: "baseline",
      header: "Baseline",
      className: "text-sm text-muted-foreground",
      cell: (row) => row.baseline ?? "—",
    },
    {
      id: "candidate",
      header: "Candidate",
      className: "text-sm font-medium",
      cell: (row) => row.candidate ?? "—",
    },
  ];

  return (
    <details
      className="rounded-lg border border-border bg-surface px-4 py-3"
      open={open}
      onToggle={(event) => {
        onOpenChange((event.currentTarget as HTMLDetailsElement).open);
      }}
    >
      <summary className="cursor-pointer text-sm font-medium text-foreground">
        Details
        <span className="ml-2 font-normal text-muted-foreground">
          logged metrics, params, columns
        </span>
      </summary>

      <div className="mt-4 flex flex-col gap-5">
        <fieldset className="flex flex-wrap gap-4">
          <legend className="mb-2 text-xs font-medium text-muted-foreground">
            Quality table columns
          </legend>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              className="size-3.5 accent-foreground"
              checked={visibleCols.has("ci")}
              onChange={(e) => toggleCol("ci", e.target.checked)}
            />
            Confidence interval
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              className="size-3.5 accent-foreground"
              checked={visibleCols.has("score")}
              onChange={(e) => toggleCol("score", e.target.checked)}
            />
            Average score
          </label>
        </fieldset>

        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">
            Logged metrics
          </h3>
          {experimentMetrics.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No experiment-level metrics were logged on these runs (for example
              latency or cost via <code className="text-xs">log_metrics</code>).
            </p>
          ) : (
            <DataTable
              rows={experimentMetrics}
              columns={metricColumns}
              getRowKey={(row) => row.key}
              selectedIndex={metricSelected}
              onSelectedIndexChange={setMetricSelected}
              onRowActivate={() => undefined}
              aria-label="Logged metrics compared"
            />
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">
            Parameter changes
          </h3>
          {params.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Candidate and baseline share the same flattened model config
              parameters.
            </p>
          ) : (
            <DataTable
              rows={params}
              columns={paramColumns}
              getRowKey={(row) => row.key}
              selectedIndex={paramSelected}
              onSelectedIndexChange={setParamSelected}
              onRowActivate={() => undefined}
              aria-label="Parameter differences"
            />
          )}
        </section>
      </div>
    </details>
  );
}
