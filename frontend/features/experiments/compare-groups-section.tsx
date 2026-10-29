"use client";

import { useMemo, useState } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDataset } from "@/features/datasets/use-datasets";
import { formatErrorForUi } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { formatDeltaPoints, formatScore } from "@/lib/format";
import { metricInfo } from "@/lib/metrics-catalog";
import { CompareStatusCell, formatCi } from "./compare-table";
import { groupableMetadataKeys, groupCompareRows, type GroupCompareRow } from "./group-compare";
import { useExperimentGroupCompare } from "./use-experiments";

const NONE = "__none__";

type CompareGroupsSectionProps = {
  experimentId: string;
  baselineId: string;
  datasetId: string;
  groupBy: string | null;
  onGroupByChange: (key: string | null) => void;
};

/**
 * Same comparison sliced by a test-case metadata field: a flat average can hide a
 * regression on one kind of question.
 */
export function CompareGroupsSection({
  experimentId,
  baselineId,
  datasetId,
  groupBy,
  onGroupByChange,
}: CompareGroupsSectionProps) {
  const datasetQuery = useDataset(datasetId);
  const keys = useMemo(
    () => groupableMetadataKeys(datasetQuery.data?.items ?? []),
    [datasetQuery.data?.items],
  );
  const groupQuery = useExperimentGroupCompare(experimentId, baselineId, groupBy);
  const rows = useMemo(() => groupCompareRows(groupQuery.data?.groups ?? []), [groupQuery.data]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const columns: DataTableColumn<GroupCompareRow>[] = useMemo(
    () => [
      {
        id: "group",
        header: groupBy ?? "Group",
        cell: (row) => (
          <span className="text-sm font-medium text-foreground">
            {row.group}
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              {row.n_items} cases
            </span>
          </span>
        ),
      },
      {
        id: "metric",
        header: "Metric",
        cell: (row) => <span className="text-sm">{metricInfo(row.evaluator_name).label}</span>,
      },
      {
        id: "baseline",
        header: "Baseline avg.",
        headerClassName: "w-[120px] text-right",
        className: "text-right tabular-nums text-sm text-muted-foreground",
        cell: (row) => formatScore(row.baseline_mean),
      },
      {
        id: "candidate",
        header: "Candidate avg.",
        headerClassName: "w-[120px] text-right",
        className: "text-right tabular-nums text-sm font-medium",
        cell: (row) => formatScore(row.candidate_mean),
      },
      {
        id: "change",
        header: "Change",
        headerClassName: "w-[160px] text-right",
        className: "text-right tabular-nums text-sm",
        cell: (row) => {
          const ci = formatCi(row.mean_ci);
          return (
            <span className="flex flex-col items-end">
              <span
                className={cn(
                  row.delta != null && row.delta < -0.0001 && "text-status-fail",
                  row.delta != null && row.delta > 0.0001 && "text-status-ok",
                )}
              >
                {formatDeltaPoints(row.delta)}
              </span>
              {ci ? (
                <span className="text-[11px] whitespace-nowrap text-muted-foreground">{ci}</span>
              ) : null}
            </span>
          );
        },
      },
      {
        id: "status",
        header: "Verdict",
        headerClassName: "w-[140px]",
        cell: (row) => <CompareStatusCell status={row.status} />,
      },
    ],
    [groupBy],
  );

  if (!datasetQuery.isLoading && keys.length === 0 && !groupBy) return null;

  return (
    <section aria-labelledby="compare-groups-title" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <h2 id="compare-groups-title" className="text-base font-semibold text-foreground">
            By group
          </h2>
          <p className="text-sm text-muted-foreground">
            Split the comparison by a test-case field to catch a drop that the overall average
            hides.
          </p>
        </div>
        <div className="w-[220px]">
          <label htmlFor="compare-group-by" className="sr-only">
            Group by
          </label>
          <Select
            value={groupBy ?? NONE}
            onValueChange={(v) => onGroupByChange(v && v !== NONE ? v : null)}
            disabled={datasetQuery.isLoading}
          >
            <SelectTrigger id="compare-group-by" className="w-full">
              <SelectValue placeholder="Group by…" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>No grouping</SelectItem>
              {keys.map((key) => (
                <SelectItem key={key} value={key}>
                  {key}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {!groupBy ? null : groupQuery.isLoading ? (
        <LoadingBlock className="min-h-[120px]" />
      ) : groupQuery.isError ? (
        <ErrorState
          title="Could not group the comparison"
          message={formatErrorForUi(groupQuery.error)}
          onRetry={() => groupQuery.refetch()}
        />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No metric to compare in these groups.</p>
      ) : (
        <DataTable
          aria-label={`Comparison by ${groupBy}`}
          columns={columns}
          rows={rows}
          getRowKey={(row) => `${row.group}:${row.evaluator_id}`}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => undefined}
        />
      )}
    </section>
  );
}
