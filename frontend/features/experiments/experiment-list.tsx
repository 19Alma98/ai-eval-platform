"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { formatErrorForUi } from "@/lib/api/client";
import type { Experiment } from "@/lib/api/types";
import { resolveLabel } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useDatasets } from "@/features/datasets/use-datasets";
import { CreateExperimentDialog } from "./create-experiment-dialog";
import { experimentModel, experimentVersion } from "./experiment-meta";
import {
  experimentsQueryOptions,
  useExperiments,
} from "./use-experiments";

export function ExperimentList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const query = useExperiments(projectId);
  const datasetsQuery = useDatasets(projectId);
  const queryOpts = projectId ? experimentsQueryOptions(projectId) : null;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  const rows = query.data ?? [];

  const datasetNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of datasetsQuery.data ?? []) {
      map.set(d.id, d.name);
    }
    return map;
  }, [datasetsQuery.data]);

  const onRowActivate = useCallback(
    (experiment: Experiment) => {
      if (!projectId) return;
      router.push(
        withProjectQuery(
          `/experiments/${encodeURIComponent(experiment.id)}`,
          projectId,
        ),
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
        cell: (row) => <StatusBadge status={row.status} kind="experiment" />,
      },
      {
        id: "dataset_id",
        header: "Dataset",
        headerClassName: "w-[160px]",
        cell: (row) => {
          const label = resolveLabel(
            row.dataset_id,
            datasetNameById,
            "Unknown dataset",
          );
          if (!projectId) {
            return <span className="text-sm text-muted-foreground">{label}</span>;
          }
          return (
            <Link
              href={withProjectQuery(
                `/datasets/${encodeURIComponent(row.dataset_id)}`,
                projectId,
              )}
              className="text-sm text-primary hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {label}
            </Link>
          );
        },
      },
      {
        id: "model",
        header: "Model",
        cell: (row) => (
          <span className="text-sm text-muted-foreground">
            {experimentModel(row) ?? "—"}
          </span>
        ),
      },
      {
        id: "version",
        header: "Version",
        cell: (row) => (
          <span className="text-sm text-muted-foreground">
            {experimentVersion(row) ?? "—"}
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
    [datasetNameById, projectId],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load runs"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center gap-3 border-b border-border bg-background px-1 pb-3">
        <div className="flex-1" />
        {projectId && rows.length > 0 ? (
          <CreateExperimentDialog
            projectId={projectId}
            open={createOpen}
            onOpenChange={setCreateOpen}
          />
        ) : null}
        {queryOpts ? (
          <RefreshControl
            queryKey={queryOpts.queryKey}
            dataUpdatedAt={query.dataUpdatedAt}
          />
        ) : null}
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="No runs yet"
          description="Create a run to execute evaluators against a test set."
          action={
            projectId ? (
              <CreateExperimentDialog
                projectId={projectId}
                open={createOpen}
                onOpenChange={setCreateOpen}
              />
            ) : null
          }
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={onRowActivate}
          aria-label="Runs"
        />
      )}
    </div>
  );
}
