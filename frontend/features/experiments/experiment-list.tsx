"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Columns3 } from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { formatErrorForUi } from "@/lib/api/client";
import type { Experiment } from "@/lib/api/types";
import { resolveLabel } from "@/lib/format";
import { experimentsCompareHref } from "@/lib/links";
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
  const searchParams = useSearchParams();
  const initialDatasetId = searchParams.get("dataset") ?? undefined;
  const [createOpen, setCreateOpen] = useState(
    () => searchParams.get("new") === "1",
  );

  const rows = useMemo(() => query.data ?? [], [query.data]);

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

  const experimentNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of rows) map.set(e.id, e.name);
    return map;
  }, [rows]);

  const columns: DataTableColumn<Experiment>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Experiment",
        cell: (row) => {
          const version = experimentVersion(row);
          return (
            <span className="flex min-w-0 flex-col">
              <span className="truncate font-medium text-foreground">{row.name}</span>
              {version && version !== row.name ? (
                <span className="truncate text-xs text-muted-foreground">{version}</span>
              ) : null}
            </span>
          );
        },
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[120px]",
        cell: (row) => <StatusBadge status={row.status} kind="experiment" />,
      },
      {
        id: "dataset_id",
        header: "Test set",
        cell: (row) => {
          const label = resolveLabel(
            row.dataset_id,
            datasetNameById,
            "Deleted test set",
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
              className="text-sm text-foreground hover:text-primary hover:underline"
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
        id: "baseline",
        header: "Compared with",
        cell: (row) =>
          row.baseline_experiment_id ? (
            <span className="text-sm text-muted-foreground">
              {resolveLabel(row.baseline_experiment_id, experimentNameById, "Earlier experiment")}
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">—</span>
          ),
      },
      {
        id: "created_at",
        header: "Created",
        headerClassName: "w-[140px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
    ],
    [datasetNameById, experimentNameById, projectId],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message = formatErrorForUi(err);
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
      <PageIntro
        title="Experiments"
        glossary="Each experiment runs one version of your app on a test set and scores every answer. Compare two experiments to see what improved."
        actions={
          <>
            {queryOpts ? (
              <RefreshControl
                queryKey={queryOpts.queryKey}
                dataUpdatedAt={query.dataUpdatedAt}
              />
            ) : null}
            {projectId && rows.length > 1 ? (
              <Button
                size="sm"
                variant="outline"
                render={<Link href={experimentsCompareHref(projectId, [])} />}
              >
                <Columns3 className="size-4" />
                Compare all
              </Button>
            ) : null}
            {projectId && rows.length > 0 ? (
              <CreateExperimentDialog
                projectId={projectId}
                open={createOpen}
                onOpenChange={setCreateOpen}
                initialDatasetId={initialDatasetId}
              />
            ) : null}
          </>
        }
      />

      {rows.length === 0 ? (
        <EmptyState
          title="No experiments yet"
          description="Create an experiment, run your app on a test set with the SDK, and every answer gets scored against your metrics."
          action={
            projectId ? (
              <CreateExperimentDialog
                projectId={projectId}
                open={createOpen}
                onOpenChange={setCreateOpen}
                initialDatasetId={initialDatasetId}
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
          aria-label="Experiments"
        />
      )}
    </div>
  );
}
