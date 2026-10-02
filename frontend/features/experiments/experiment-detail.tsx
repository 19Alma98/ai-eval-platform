"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { useDatasets } from "@/features/datasets/use-datasets";
import { useTaskTypes } from "@/features/datasets/use-task-types";
import { CreateEvaluatorDialog } from "./create-evaluator-dialog";
import { withProjectQuery } from "@/lib/project-href";
import { ArrowLeft, GitCompare, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api/client";
import { evaluateExperiment } from "@/lib/api/experiments";
import type { Dataset, EvaluatorSummary } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import {
  experimentQueryOptions,
  experimentSummaryQueryKey,
  experimentSummaryQueryOptions,
  useEvaluators,
  useExperiment,
  useExperimentSummary,
} from "./use-experiments";
import { experimentModel, experimentVersion } from "./experiment-meta";

function formatScore(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

function formatPassRate(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function evaluatorKind(ev: { config: Record<string, unknown> }): string | null {
  const kind = ev.config?.kind;
  return typeof kind === "string" && kind.trim() ? kind.trim() : null;
}

type ExperimentDetailViewProps = {
  projectId: string;
  experimentId: string;
};

export function ExperimentDetailView({
  projectId,
  experimentId,
}: ExperimentDetailViewProps) {
  const experimentQuery = useExperiment(experimentId);
  const summaryQuery = useExperimentSummary(experimentId);
  const datasetsQuery = useDatasets(projectId);
  const taskTypesQuery = useTaskTypes();
  const summaryOpts = experimentSummaryQueryOptions(experimentId);
  const [evaluateOpen, setEvaluateOpen] = useState(false);
  const [createEvaluatorOpen, setCreateEvaluatorOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const experiment = experimentQuery.data;
  const evaluators = summaryQuery.data?.evaluators ?? [];

  const datasetById = useMemo(() => {
    const map = new Map<string, Dataset>();
    for (const d of datasetsQuery.data ?? []) {
      map.set(d.id, d);
    }
    return map;
  }, [datasetsQuery.data]);

  const compareHref = useMemo(() => {
    let href = `/experiments/${encodeURIComponent(experimentId)}/compare`;
    if (experiment?.baseline_experiment_id) {
      href += `?baseline=${encodeURIComponent(experiment.baseline_experiment_id)}`;
    }
    return withProjectQuery(href, projectId);
  }, [experiment?.baseline_experiment_id, experimentId, projectId]);

  const releaseHref = withProjectQuery(
    `/release?experiment=${encodeURIComponent(experimentId)}`,
    projectId,
  );

  const columns: DataTableColumn<EvaluatorSummary>[] = useMemo(
    () => [
      {
        id: "evaluator",
        header: "Evaluator",
        cell: (row) => (
          <span className="font-medium text-foreground">
            {row.evaluator_name?.trim() ||
              truncateId(row.evaluator_id, 10)}
          </span>
        ),
      },
      {
        id: "mean_score",
        header: "Mean score",
        headerClassName: "w-[112px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatScore(row.mean_score),
      },
      {
        id: "pass_rate",
        header: "Pass rate",
        headerClassName: "w-[96px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatPassRate(row.pass_rate),
      },
      {
        id: "n_scored",
        header: "Scored",
        headerClassName: "w-[72px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.n_scored,
      },
      {
        id: "n_error",
        header: "Errors",
        headerClassName: "w-[72px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.n_error,
      },
      {
        id: "n_skipped",
        header: "Skipped",
        headerClassName: "w-[80px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.n_skipped,
      },
      {
        id: "n_items",
        header: "Items",
        headerClassName: "w-[72px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.n_items,
      },
    ],
    [],
  );

  const isLoading = experimentQuery.isLoading || summaryQuery.isLoading;
  const isError = experimentQuery.isError || summaryQuery.isError;

  if (isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (isError) {
    const err = experimentQuery.error ?? summaryQuery.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Could not load experiment"
        message={message}
        onRetry={() => {
          void experimentQuery.refetch();
          void summaryQuery.refetch();
        }}
      />
    );
  }

  if (!experiment) {
    return null;
  }

  const backHref = withProjectQuery("/experiments", projectId);

  const dataset = datasetById.get(experiment.dataset_id);
  const datasetLabel =
    dataset?.name ?? truncateId(experiment.dataset_id, 10);
  const datasetHref = withProjectQuery(
    `/datasets/${encodeURIComponent(experiment.dataset_id)}`,
    projectId,
  );
  const taskInfo = (taskTypesQuery.data ?? []).find(
    (t) => t.id === dataset?.task_type,
  );
  const recommendedKinds = taskInfo?.recommended_evaluator_kinds ?? [];
  const modelLabel = experimentModel(experiment);
  const versionLabel = experimentVersion(experiment);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href={backHref} />}
            >
              <ArrowLeft className="size-4" />
              Back
            </Button>
            <h1 className="text-lg font-semibold text-foreground">
              {experiment.name}
            </h1>
            <StatusBadge status={experiment.status} />
          </div>
          <p className="text-sm text-muted-foreground">
            Flow: Evaluate (scores) → Compare (delta vs baseline) → Release
            (gate).
          </p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              Dataset{" "}
              <Link
                href={datasetHref}
                className="text-primary hover:underline"
              >
                {datasetLabel}
              </Link>
              {taskInfo ? (
                <Badge variant="secondary">{taskInfo.label}</Badge>
              ) : null}
            </span>
            {modelLabel ? <span>Model {modelLabel}</span> : null}
            {versionLabel ? <span>Version {versionLabel}</span> : null}
            <span>
              Created <RelativeTime date={experiment.created_at} />
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <EvaluateDialog
            projectId={projectId}
            experimentId={experimentId}
            recommendedKinds={recommendedKinds}
            open={evaluateOpen}
            onOpenChange={setEvaluateOpen}
            onCreateEvaluator={() => {
              setEvaluateOpen(false);
              setCreateEvaluatorOpen(true);
            }}
          />
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href={compareHref} />}
          >
            <GitCompare className="size-4" />
            Compare
          </Button>
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href={releaseHref} />}
          >
            <ShieldCheck className="size-4" />
            Release
          </Button>
          <RefreshControl
            queryKey={summaryOpts.queryKey}
            dataUpdatedAt={summaryQuery.dataUpdatedAt}
          />
        </div>
      </div>

      <h2 className="text-sm font-medium text-foreground">Summary</h2>

      {evaluators.length === 0 ? (
        <EmptyState
          title="No evaluation runs"
          description="Run evaluators against this experiment to see aggregated metrics."
        />
      ) : (
        <DataTable
          rows={evaluators}
          columns={columns}
          getRowKey={(row) => row.run_id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => {}}
          aria-label="Experiment evaluator summary"
        />
      )}
      <CreateEvaluatorDialog
        projectId={projectId}
        open={createEvaluatorOpen}
        onOpenChange={setCreateEvaluatorOpen}
      />
    </div>
  );
}

function EvaluateDialog({
  projectId,
  experimentId,
  recommendedKinds,
  open,
  onOpenChange,
  onCreateEvaluator,
}: {
  projectId: string;
  experimentId: string;
  recommendedKinds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreateEvaluator: () => void;
}) {
  const queryClient = useQueryClient();
  const evaluatorsQuery = useEvaluators(projectId);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const recommendedSet = useMemo(
    () => new Set(recommendedKinds),
    [recommendedKinds],
  );

  const evaluate = useMutation({
    mutationFn: () =>
      evaluateExperiment(experimentId, {
        evaluator_ids: [...selectedIds],
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: experimentSummaryQueryKey(experimentId),
      });
      await queryClient.invalidateQueries({
        queryKey: experimentQueryOptions(experimentId).queryKey,
      });
      toast.success("Evaluation started");
      setSelectedIds(new Set());
      onOpenChange(false);
    },
    onError: (err) => {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Evaluate failed";
      toast.error(message);
    },
  });

  function toggleId(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectRecommended() {
    const evaluators = evaluatorsQuery.data ?? [];
    const next = new Set<string>();
    for (const ev of evaluators) {
      const kind = evaluatorKind(ev);
      if (kind && recommendedSet.has(kind)) {
        next.add(ev.id);
      }
    }
    setSelectedIds(next);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (selectedIds.size === 0) return;
    evaluate.mutate();
  }

  const evaluators = evaluatorsQuery.data ?? [];
  const sortedEvaluators = useMemo(() => {
    return [...evaluators].sort((a, b) => {
      const aRec = recommendedSet.has(evaluatorKind(a) ?? "") ? 0 : 1;
      const bRec = recommendedSet.has(evaluatorKind(b) ?? "") ? 0 : 1;
      if (aRec !== bRec) return aRec - bRec;
      return a.name.localeCompare(b.name);
    });
  }, [evaluators, recommendedSet]);
  const hasRecommendedPresent = sortedEvaluators.some((ev) =>
    recommendedSet.has(evaluatorKind(ev) ?? ""),
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button type="button" size="sm">
            Evaluate
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Run evaluators</DialogTitle>
            <DialogDescription>
              Select one or more evaluators to run against this experiment.
              {recommendedKinds.length > 0
                ? ` Recommended for this dataset task: ${recommendedKinds.join(", ")}.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[280px] flex-col gap-2 overflow-y-auto py-4">
            {evaluatorsQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading evaluators…</p>
            ) : evaluators.length === 0 ? (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  No evaluators in this project yet.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={onCreateEvaluator}
                >
                  Create evaluator
                </Button>
              </div>
            ) : (
              <>
                {hasRecommendedPresent ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="self-start"
                    onClick={selectRecommended}
                  >
                    Select recommended
                  </Button>
                ) : recommendedKinds.length > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No project evaluators match recommended kinds yet. Create
                    ones with config.kind in: {recommendedKinds.join(", ")}.
                  </p>
                ) : null}
                {sortedEvaluators.map((ev) => {
                  const kind = evaluatorKind(ev);
                  const isRecommended = kind != null && recommendedSet.has(kind);
                  return (
                    <label
                      key={ev.id}
                      className="flex cursor-pointer items-center gap-3 rounded-md border border-border px-3 py-2 hover:bg-surface"
                    >
                      <input
                        type="checkbox"
                        className="size-4 rounded border-border"
                        checked={selectedIds.has(ev.id)}
                        onChange={() => toggleId(ev.id)}
                      />
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                          {ev.name}
                          {isRecommended ? (
                            <Badge variant="secondary">recommended</Badge>
                          ) : null}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">
                          {ev.type}
                          {kind ? ` · ${kind}` : ""} · v{ev.version}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={selectedIds.size === 0 || evaluate.isPending}
            >
              {evaluate.isPending ? "Running…" : "Run selected"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
