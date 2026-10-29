"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
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
import { summarizeProjectExperiments } from "@/lib/api/experiments";
import type { Experiment, ExperimentSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { resolveLabel } from "@/lib/format";
import { experimentsCompareHref } from "@/lib/links";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useDatasets } from "@/features/datasets/use-datasets";
import { CreateExperimentDialog } from "./create-experiment-dialog";
import { ExperimentAliasBadges } from "./experiment-alias-actions";
import { aliasesByExperimentId } from "./experiment-aliases";
import { experimentModel, experimentVersion } from "./experiment-meta";
import { tallyTargets } from "./metric-target";
import { useExperimentAliases } from "./use-experiment-aliases";
import {
  experimentsQueryOptions,
  useExperiments,
} from "./use-experiments";

export function ExperimentList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const query = useExperiments(projectId);
  const datasetsQuery = useDatasets(projectId);
  const aliasesQuery = useExperimentAliases(projectId);
  const queryOpts = projectId ? experimentsQueryOptions(projectId) : null;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const searchParams = useSearchParams();
  const initialDatasetId = searchParams.get("dataset") ?? undefined;
  const [createOpen, setCreateOpen] = useState(
    () => searchParams.get("new") === "1",
  );

  const rows = useMemo(() => query.data ?? [], [query.data]);
  const aliasNamesByExperiment = useMemo(
    () => aliasesByExperimentId(aliasesQuery.data ?? []),
    [aliasesQuery.data],
  );
  // Same key as the "Compare all" matrix with nothing pinned, so both share the cache.
  const summariesQuery = useQuery({
    queryKey: ["experiment-summaries", projectId, ""],
    queryFn: () => summarizeProjectExperiments(projectId!),
    enabled: !!projectId && rows.length > 0,
  });
  const summaryById = useMemo(() => {
    const map = new Map<string, ExperimentSummary>();
    for (const s of summariesQuery.data ?? []) map.set(s.experiment_id, s);
    return map;
  }, [summariesQuery.data]);
  const anyBaseline = rows.some((r) => r.baseline_experiment_id);

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
          const aliasNames = aliasNamesByExperiment.get(row.id) ?? [];
          return (
            <span className="flex min-w-0 flex-col">
              <span className="truncate font-medium text-foreground">{row.name}</span>
              {version && version !== row.name ? (
                <span className="truncate text-xs text-muted-foreground">{version}</span>
              ) : null}
              <ExperimentAliasBadges names={aliasNames} />
            </span>
          );
        },
      },
      {
        id: "results",
        header: "Metrics meeting target",
        headerClassName: "w-[220px]",
        cell: (row) => (
          <ResultsCell
            summary={summaryById.get(row.id)}
            loading={summariesQuery.isLoading}
          />
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
      ...(anyBaseline
        ? [
            {
              id: "baseline",
              header: "Compared with",
              cell: (row: Experiment) =>
                row.baseline_experiment_id ? (
                  <span className="text-sm text-muted-foreground">
                    {resolveLabel(
                      row.baseline_experiment_id,
                      experimentNameById,
                      "Earlier experiment",
                    )}
                  </span>
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                ),
            },
          ]
        : []),
      {
        id: "created_at",
        header: "Created",
        headerClassName: "w-[140px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
    ],
    [
      aliasNamesByExperiment,
      anyBaseline,
      datasetNameById,
      experimentNameById,
      projectId,
      summariesQuery.isLoading,
      summaryById,
    ],
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

/** "7 of 10" with a segmented bar: one segment per metric, red for those below target. */
function ResultsCell({
  summary,
  loading,
}: {
  summary: ExperimentSummary | undefined;
  loading: boolean;
}) {
  if (loading) {
    return <span className="block h-2 w-24 animate-pulse rounded-full bg-surface-2" aria-hidden />;
  }
  const tally = tallyTargets(summary?.evaluators ?? []);
  if (tally.total === 0) {
    return <span className="text-sm text-muted-foreground">Not scored yet</span>;
  }
  const allMet = tally.met === tally.total;
  return (
    <span
      className="flex flex-col gap-1"
      aria-label={`${tally.met} of ${tally.total} metrics meet their target`}
    >
      <span className="text-sm tabular-nums">
        <span
          className={cn(
            "font-semibold",
            allMet ? "text-status-ok" : tally.missed > 0 ? "text-status-fail" : "text-foreground",
          )}
        >
          {tally.met} of {tally.total}
        </span>
      </span>
      <span className="flex h-1.5 w-full max-w-[160px] gap-0.5" aria-hidden>
        {Array.from({ length: tally.total }, (_, i) => (
          <span
            key={i}
            className={cn(
              "flex-1 rounded-full",
              i < tally.met
                ? "bg-status-ok"
                : i < tally.met + tally.missed
                  ? "bg-status-fail"
                  : "bg-surface-2",
            )}
          />
        ))}
      </span>
    </span>
  );
}
