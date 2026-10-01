"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { ApiError } from "@/lib/api/client";
import type { Experiment } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import { useProjectId } from "@/lib/project-store";
import {
  experimentsQueryOptions,
  useExperiments,
} from "./use-experiments";

export function ExperimentList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const query = useExperiments(projectId);
  const queryOpts = projectId ? experimentsQueryOptions(projectId) : null;
  const [selectedIndex, setSelectedIndex] = useState(0);

  const rows = query.data ?? [];

  const onRowActivate = useCallback(
    (experiment: Experiment) => {
      if (!projectId) return;
      router.push(
        `/experiments/${encodeURIComponent(experiment.id)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<Experiment>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Name",
        cell: (row) => (
          <span className="font-medium text-foreground">{row.name}</span>
        ),
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[120px]",
        cell: (row) => <StatusBadge status={row.status} />,
      },
      {
        id: "dataset_id",
        header: "Dataset",
        headerClassName: "w-[140px]",
        cell: (row) => (
          <span className="font-mono text-xs text-muted-foreground">
            {truncateId(row.dataset_id, 10)}
          </span>
        ),
      },
      {
        id: "application_version",
        header: "App version",
        cell: (row) => (
          <span className="text-sm text-muted-foreground">
            {row.application_version?.trim() || "—"}
          </span>
        ),
      },
      {
        id: "created_at",
        header: "Created",
        headerClassName: "w-[120px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
    ],
    [],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Could not load experiments"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center gap-3 border-b border-border bg-background px-1 pb-3">
        <h1 className="text-lg font-semibold text-foreground">Experiments</h1>
        <div className="flex-1" />
        {queryOpts ? (
          <RefreshControl
            queryKey={queryOpts.queryKey}
            dataUpdatedAt={query.dataUpdatedAt}
          />
        ) : null}
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="No experiments yet"
          description="Create experiments via the API to run evaluators against datasets."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={onRowActivate}
          aria-label="Experiments"
        />
      )}
    </div>
  );
}
