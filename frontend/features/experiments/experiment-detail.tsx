"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { ArrowLeft, GitCompare, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
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
import type { EvaluatorSummary } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import {
  experimentQueryOptions,
  experimentSummaryQueryKey,
  experimentSummaryQueryOptions,
  useEvaluators,
  useExperiment,
  useExperimentSummary,
} from "./use-experiments";

function formatScore(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

function formatPassRate(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
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
  const summaryOpts = experimentSummaryQueryOptions(experimentId);
  const [evaluateOpen, setEvaluateOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const experiment = experimentQuery.data;
  const evaluators = summaryQuery.data?.evaluators ?? [];

  const compareHref = useMemo(() => {
    const base = `/experiments/${encodeURIComponent(experimentId)}/compare`;
    const params = new URLSearchParams({ project: projectId });
    if (experiment?.baseline_experiment_id) {
      params.set("baseline", experiment.baseline_experiment_id);
    }
    return `${base}?${params.toString()}`;
  }, [experiment?.baseline_experiment_id, experimentId, projectId]);

  const releaseHref = `/release?project=${encodeURIComponent(projectId)}&experiment=${encodeURIComponent(experimentId)}`;

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

  const backHref = `/experiments?project=${encodeURIComponent(projectId)}`;

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
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>
              Dataset{" "}
              <span className="font-mono text-xs text-foreground">
                {truncateId(experiment.dataset_id, 12)}
              </span>
            </span>
            {experiment.application_version ? (
              <span>Version {experiment.application_version}</span>
            ) : null}
            <span>
              Created <RelativeTime date={experiment.created_at} />
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <EvaluateDialog
            projectId={projectId}
            experimentId={experimentId}
            open={evaluateOpen}
            onOpenChange={setEvaluateOpen}
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
    </div>
  );
}

function EvaluateDialog({
  projectId,
  experimentId,
  open,
  onOpenChange,
}: {
  projectId: string;
  experimentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const evaluatorsQuery = useEvaluators(projectId);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

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

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (selectedIds.size === 0) return;
    evaluate.mutate();
  }

  const evaluators = evaluatorsQuery.data ?? [];

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
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[280px] flex-col gap-2 overflow-y-auto py-4">
            {evaluatorsQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading evaluators…</p>
            ) : evaluators.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No evaluators in this project. Create evaluators via the API first.
              </p>
            ) : (
              evaluators.map((ev) => (
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
                  <span className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium text-foreground">
                      {ev.name}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {ev.type} · v{ev.version}
                    </span>
                  </span>
                </label>
              ))
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
