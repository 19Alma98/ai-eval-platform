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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatErrorForUi } from "@/lib/api/client";
import { summarizeProjectExperiments } from "@/lib/api/experiments";
import type { Experiment, ExperimentSummary } from "@/lib/api/types";
import { useCanWrite } from "@/lib/auth-context";
import { cn } from "@/lib/cn";
import { formatScore, resolveLabel } from "@/lib/format";
import { experimentsCompareHref } from "@/lib/links";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useDatasets } from "@/features/datasets/use-datasets";
import { CreateExperimentDialog } from "./create-experiment-dialog";
import {
  ExperimentAliasActions,
  ExperimentAliasBadges,
} from "./experiment-alias-actions";
import { aliasesByExperimentId } from "./experiment-aliases";
import { buildMatrix } from "./experiment-matrix";
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
  const writable = useCanWrite();
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

  const allRows = useMemo(() => query.data ?? [], [query.data]);
  const datasetFilter = searchParams.get("dataset");
  const rows = useMemo(() => {
    if (!datasetFilter) return allRows;
    return allRows.filter((r) => r.dataset_id === datasetFilter);
  }, [allRows, datasetFilter]);

  const aliasNamesByExperiment = useMemo(
    () => aliasesByExperimentId(aliasesQuery.data ?? []),
    [aliasesQuery.data],
  );
  // Same key as the "Compare all" matrix with nothing pinned, so both share the cache.
  const summariesQuery = useQuery({
    queryKey: ["experiment-summaries", projectId, ""],
    queryFn: () => summarizeProjectExperiments(projectId!),
    enabled: !!projectId && allRows.length > 0,
  });
  const summaryById = useMemo(() => {
    const map = new Map<string, ExperimentSummary>();
    for (const s of summariesQuery.data ?? []) map.set(s.experiment_id, s);
    return map;
  }, [summariesQuery.data]);
  const matrix = useMemo(
    () => buildMatrix(rows, summariesQuery.data ?? []),
    [rows, summariesQuery.data],
  );
  const metricsByExperiment = useMemo(() => {
    const map = new Map<string, (typeof matrix.rows)[number]["metrics"]>();
    for (const row of matrix.rows) map.set(row.experiment.id, row.metrics);
    return map;
  }, [matrix]);
  const anyBaseline = rows.some((r) => r.baseline_experiment_id);

  const datasetLabelById = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of datasetsQuery.data ?? []) {
      map.set(d.id, `${d.name} · v${d.version}`);
    }
    return map;
  }, [datasetsQuery.data]);

  const datasetFilterOptions = useMemo(() => {
    const used = new Set(allRows.map((r) => r.dataset_id));
    return (datasetsQuery.data ?? [])
      .filter((d) => used.has(d.id))
      .sort((a, b) => a.name.localeCompare(b.name) || b.version - a.version);
  }, [allRows, datasetsQuery.data]);

  function setDatasetFilter(id: string | null) {
    if (!projectId) return;
    const params = new URLSearchParams(searchParams.toString());
    if (id) params.set("dataset", id);
    else params.delete("dataset");
    params.set("project", projectId);
    const qs = params.toString();
    router.replace(qs ? `/experiments?${qs}` : "/experiments");
  }

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
    for (const e of allRows) map.set(e.id, e.name);
    return map;
  }, [allRows]);

  const columns: DataTableColumn<Experiment>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Experiment",
        cell: (row) => {
          const version = experimentVersion(row);
          const aliasNames = aliasNamesByExperiment.get(row.id) ?? [];
          return (
            <span className="flex min-w-0 flex-col gap-1">
              <span className="truncate font-medium text-foreground">{row.name}</span>
              {version && version !== row.name ? (
                <span className="truncate text-xs text-muted-foreground">{version}</span>
              ) : null}
              <ExperimentAliasBadges names={aliasNames} />
              {writable && projectId ? (
                <span
                  className="flex flex-wrap gap-1"
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <ExperimentAliasActions
                    projectId={projectId}
                    experiment={row}
                    experimentNames={experimentNameById}
                    showBadges={false}
                  />
                </span>
              ) : null}
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
      ...matrix.columns.map(
        (col): DataTableColumn<Experiment> => ({
          id: `metric:${col.key}`,
          header: col.label,
          headerClassName: "w-[100px] text-right",
          className: "text-right tabular-nums text-sm",
          cell: (row) => {
            if (summariesQuery.isLoading) {
              return (
                <span className="inline-block h-3 w-10 animate-pulse rounded bg-surface-2" />
              );
            }
            const mean = metricsByExperiment.get(row.id)?.[col.key]?.mean;
            return mean == null ? "—" : formatScore(mean);
          },
        }),
      ),
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
            datasetLabelById,
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
      datasetLabelById,
      experimentNameById,
      matrix.columns,
      metricsByExperiment,
      projectId,
      summariesQuery.isLoading,
      summaryById,
      writable,
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
            {writable && projectId && rows.length > 0 ? (
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

      {allRows.length === 0 ? (
        <EmptyState
          title="No experiments yet"
          description="Create an experiment, run your app on a test set with the SDK, and every answer gets scored against your metrics."
          action={
            writable && projectId ? (
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
        <>
          {datasetFilterOptions.length > 1 ? (
            <div className="flex flex-wrap items-center gap-2">
              <label
                htmlFor="experiments-dataset-filter"
                className="text-sm text-muted-foreground"
              >
                Test set
              </label>
              <Select
                value={datasetFilter ?? "__all__"}
                onValueChange={(v) =>
                  setDatasetFilter(!v || v === "__all__" ? null : v)
                }
              >
                <SelectTrigger
                  id="experiments-dataset-filter"
                  className="h-8 w-[260px]"
                  aria-label="Filter by test set version"
                >
                  <SelectValue placeholder="All test sets" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All test sets</SelectItem>
                  {datasetFilterOptions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name} · v{d.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
          {rows.length === 0 ? (
            <EmptyState
              title="No experiments for this test set"
              description="Clear the filter or pick another test set version."
              action={
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setDatasetFilter(null)}
                >
                  Show all
                </Button>
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
        </>
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
