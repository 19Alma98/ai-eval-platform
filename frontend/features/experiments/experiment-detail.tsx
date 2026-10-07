"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type SubmitEvent, type ReactNode } from "react";
import { formatConfigValue } from "@/features/app-configs/format-config-value";
import { RAG_RECOMMENDED_EVALUATOR_KINDS } from "@/features/datasets/rag-qa";
import { useDatasets, useDataset } from "@/features/datasets/use-datasets";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatErrorForUi } from "@/lib/api/client";
import { evaluateExperiment, evaluatePack } from "@/lib/api/experiments";
import type { Dataset, EvaluatorSummary } from "@/lib/api/types";
import { toastEvaluateOutcome } from "@/features/experiments/evaluate-outcome";
import { evaluatePackBody } from "@/features/metrics/metrics-set-submit";
import {
  useMetricsSet,
  useMetricsSets,
} from "@/features/metrics/use-metrics-sets";
import { CopyTechnicalId } from "@/components/copy-technical-id";
import { resolveLabel } from "@/lib/format";
import {
  experimentQueryOptions,
  experimentOutputsQueryKey,
  experimentSummaryQueryKey,
  experimentSummaryQueryOptions,
  useEvaluators,
  useEvaluationRun,
  useExperiment,
  useExperimentOutputs,
  useExperimentSummary,
} from "./use-experiments";
import { RunItemTimeline } from "./run-item-timeline";
import {
  buildRunItemViews,
  shouldRenderRunItemsSection,
  type RunItemView,
} from "./run-items";
import {
  experimentAppConfigChip,
  experimentAppConfigSnapshot,
  experimentModel,
  experimentVersion,
  metricsSetBoundLabel,
} from "./experiment-meta";

function formatScore(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

function formatPassRate(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

const PREVIEW_MAX = 96;

function valuePreview(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function truncatePreview(text: string, max = PREVIEW_MAX): string {
  if (text === "—") return text;
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function runContextWithoutDocuments(context: unknown): unknown {
  if (typeof context !== "object" || context === null || Array.isArray(context)) {
    return context;
  }
  const { documents: _documents, ...rest } = context as Record<string, unknown>;
  return rest;
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function DetailBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <div className="max-h-[200px] overflow-auto rounded-md border border-border bg-surface p-3 text-sm whitespace-pre-wrap break-words text-foreground">
        {children}
      </div>
    </div>
  );
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
  const metricsSetsQuery = useMetricsSets(projectId);
  const boundMetricsSetId = experimentQuery.data?.metrics_set_id ?? null;
  const boundSetInList = useMemo(
    () =>
      boundMetricsSetId
        ? (metricsSetsQuery.data ?? []).find((s) => s.id === boundMetricsSetId)
        : undefined,
    [boundMetricsSetId, metricsSetsQuery.data],
  );
  const boundSetDetailQuery = useMetricsSet(
    boundMetricsSetId && !boundSetInList ? boundMetricsSetId : null,
  );
  const summaryOpts = experimentSummaryQueryOptions(experimentId);
  const [evaluateOpen, setEvaluateOpen] = useState(false);
  const [createEvaluatorOpen, setCreateEvaluatorOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedItemIndex, setSelectedItemIndex] = useState(0);

  const experiment = experimentQuery.data;
  const evaluators = summaryQuery.data?.evaluators ?? [];
  const selectedRunId = evaluators[selectedIndex]?.run_id ?? null;
  const runQuery = useEvaluationRun(selectedRunId);
  const outputsQuery = useExperimentOutputs(experimentId);
  const datasetDetailQuery = useDataset(experiment?.dataset_id ?? null);
  const evaluatorsRegistryQuery = useEvaluators(projectId);

  const datasetById = useMemo(() => {
    const map = new Map<string, Dataset>();
    for (const d of datasetsQuery.data ?? []) {
      map.set(d.id, d);
    }
    return map;
  }, [datasetsQuery.data]);

  const evaluatorNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const ev of evaluatorsRegistryQuery.data ?? []) {
      map.set(ev.id, ev.name);
    }
    return map;
  }, [evaluatorsRegistryQuery.data]);

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

  const runItemViews = useMemo(() => {
    const items = datasetDetailQuery.data?.items ?? [];
    const outputs = outputsQuery.data ?? [];
    const results = runQuery.data?.results ?? [];
    return buildRunItemViews(items, outputs, results);
  }, [datasetDetailQuery.data?.items, outputsQuery.data, runQuery.data?.results]);

  useEffect(() => {
    setSelectedItemIndex(0);
  }, [selectedRunId, runItemViews.length]);

  const itemColumns: DataTableColumn<RunItemView>[] = useMemo(
    () => [
      {
        id: "question",
        header: "Question",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-foreground">
            {truncatePreview(valuePreview(row.question))}
          </span>
        ),
      },
      {
        id: "answer",
        header: "Answer",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(valuePreview(row.actualOutput))}
          </span>
        ),
      },
      {
        id: "score",
        header: "Score",
        headerClassName: "w-[88px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatScore(row.score),
      },
      {
        id: "label",
        header: "Label",
        headerClassName: "w-[104px]",
        cell: (row) => {
          const label = row.label?.trim();
          if (!label) return "—";
          return <StatusBadge status={label} />;
        },
      },
      {
        id: "explanation",
        header: "Explanation",
        cell: (row) => {
          const text = row.explanation?.trim() || "";
          if (!text) return "—";
          return (
            <span
              className="line-clamp-2 text-xs text-muted-foreground"
              title={text}
            >
              {text}
            </span>
          );
        },
      },
    ],
    [],
  );

  const columns: DataTableColumn<EvaluatorSummary>[] = useMemo(
    () => [
      {
        id: "evaluator",
        header: "Evaluator",
        cell: (row) => (
          <span className="font-medium text-foreground">
            {row.evaluator_name?.trim() ||
              resolveLabel(
                row.evaluator_id,
                evaluatorNameById,
                "Unknown evaluator",
              )}
          </span>
        ),
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[104px]",
        cell: (row) =>
          row.status?.trim() ? <StatusBadge status={row.status} /> : "—",
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
        cell: (row) => (
          <span
            className={
              row.n_error > 0
                ? "font-medium text-status-fail"
                : undefined
            }
          >
            {row.n_error}
          </span>
        ),
      },
      {
        id: "n_skipped",
        header: "Skipped",
        headerClassName: "w-[80px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => (
          <span
            className={
              row.n_skipped > 0
                ? "font-medium text-status-warn"
                : undefined
            }
          >
            {row.n_skipped}
          </span>
        ),
      },
      {
        id: "n_items",
        header: "Items",
        headerClassName: "w-[72px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.n_items,
      },
    ],
    [evaluatorNameById],
  );

  const isLoading = experimentQuery.isLoading || summaryQuery.isLoading;
  const isError = experimentQuery.isError || summaryQuery.isError;

  if (isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (isError) {
    const err = experimentQuery.error ?? summaryQuery.error;
    const message = formatErrorForUi(err);
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
    dataset?.name?.trim() ||
    resolveLabel(experiment.dataset_id, undefined, "Unknown dataset");
  const datasetHref = withProjectQuery(
    `/datasets/${encodeURIComponent(experiment.dataset_id)}`,
    projectId,
  );
  const recommendedKinds = [...RAG_RECOMMENDED_EVALUATOR_KINDS];
  const modelLabel = experimentModel(experiment);
  const versionLabel = experimentVersion(experiment);
  const appConfigChip = experimentAppConfigChip(experiment);
  const appConfigSnapshot = experimentAppConfigSnapshot(experiment);
  const metricsSetLabel = metricsSetBoundLabel(
    experiment,
    metricsSetsQuery.data,
    boundSetDetailQuery.data,
  );
  const appConfigHref = appConfigChip
    ? withProjectQuery(
        `/app-configs/${encodeURIComponent(appConfigChip.familyName)}`,
        projectId,
      )
    : null;

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
            </span>
            {appConfigChip && appConfigHref ? (
              <span className="inline-flex items-center gap-2">
                App config{" "}
                <Link href={appConfigHref} className="text-primary hover:underline">
                  <Badge variant="secondary" className="font-mono text-xs">
                    {appConfigChip.label}
                  </Badge>
                </Link>
              </span>
            ) : null}
            {modelLabel ? <span>Model {modelLabel}</span> : null}
            {versionLabel ? <span>Version {versionLabel}</span> : null}
            <span>Metrics set {metricsSetLabel}</span>
            <span>
              Created <RelativeTime date={experiment.created_at} />
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ScorePackControls projectId={projectId} experimentId={experimentId} />
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

      {appConfigSnapshot ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-foreground">
              App config snapshot
            </h2>
            {appConfigSnapshot.contentHash ? (
              <span className="font-mono text-xs text-muted-foreground">
                hash {appConfigSnapshot.contentHash.slice(0, 12)}…
              </span>
            ) : null}
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <DetailBlock title="Prompt">
              {formatConfigValue(appConfigSnapshot.prompt)}
            </DetailBlock>
            <DetailBlock title="Model">
              {formatConfigValue(appConfigSnapshot.model)}
            </DetailBlock>
            <DetailBlock title="Retrieval">
              {formatConfigValue(appConfigSnapshot.retrieval)}
            </DetailBlock>
          </div>
        </div>
      ) : null}

      <h2 className="text-sm font-medium text-foreground">Summary</h2>

      {evaluators.length === 0 ? (
        <EmptyState
          title="No evaluation runs"
          description="Score with the project metrics pack or run selected evaluators to see aggregated metrics. Dataset questions and bound answers are listed below."
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

      {shouldRenderRunItemsSection({
        hasEvaluationRun: Boolean(selectedRunId),
      }) ? (
        <RunItemsSection
          projectId={projectId}
          runId={selectedRunId}
          evaluatorName={
            selectedRunId
              ? evaluators[selectedIndex]?.evaluator_name?.trim() ||
                resolveLabel(
                  evaluators[selectedIndex]?.evaluator_id,
                  evaluatorNameById,
                  "Unknown evaluator",
                )
              : null
          }
          runStatus={runQuery.data?.status}
          itemsLoading={
            (selectedRunId ? runQuery.isLoading : false) ||
            outputsQuery.isLoading ||
            datasetDetailQuery.isLoading
          }
          itemsError={
            selectedRunId && runQuery.isError
              ? runQuery.error
              : outputsQuery.isError
                ? outputsQuery.error
                : datasetDetailQuery.isError
                  ? datasetDetailQuery.error
                  : null
          }
          onRetryItems={() => {
            if (selectedRunId) void runQuery.refetch();
            void outputsQuery.refetch();
            void datasetDetailQuery.refetch();
          }}
          runItems={runItemViews}
          itemColumns={itemColumns}
          selectedItemIndex={selectedItemIndex}
          onSelectedItemIndexChange={setSelectedItemIndex}
        />
      ) : null}
      <CreateEvaluatorDialog
        projectId={projectId}
        open={createEvaluatorOpen}
        onOpenChange={setCreateEvaluatorOpen}
      />
    </div>
  );
}

function useInvalidateExperimentScoring(experimentId: string) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({
      queryKey: experimentSummaryQueryKey(experimentId),
    });
    await queryClient.invalidateQueries({
      queryKey: experimentQueryOptions(experimentId).queryKey,
    });
    await queryClient.invalidateQueries({
      queryKey: experimentOutputsQueryKey(experimentId),
    });
  };
}

function ScorePackControls({
  projectId,
  experimentId,
}: {
  projectId: string;
  experimentId: string;
}) {
  const invalidate = useInvalidateExperimentScoring(experimentId);
  const [overrideOpen, setOverrideOpen] = useState(false);

  const scorePack = useMutation({
    mutationFn: () => evaluatePack(experimentId),
    onMutate: () => {
      toast.message("Scoring metrics pack…", {
        description: "LLM judges can take a minute; keep this tab open.",
      });
    },
    onSuccess: async (data) => {
      await invalidate();
      toastEvaluateOutcome(data, {
        success: "Metrics pack scoring complete",
        withErrors: "Metrics pack scoring finished with errors",
      });
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
    },
  });

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={scorePack.isPending}
        onClick={() => scorePack.mutate()}
      >
        {scorePack.isPending ? "Scoring…" : "Score with metrics pack"}
      </Button>
      <ScorePackOverrideDialog
        projectId={projectId}
        experimentId={experimentId}
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        scoringPending={scorePack.isPending}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOverrideOpen(true)}
        disabled={scorePack.isPending}
      >
        Override metrics set…
      </Button>
    </>
  );
}

function ScorePackOverrideDialog({
  projectId,
  experimentId,
  open,
  onOpenChange,
  scoringPending,
}: {
  projectId: string;
  experimentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scoringPending: boolean;
}) {
  const metricsSetsQuery = useMetricsSets(projectId);
  const invalidate = useInvalidateExperimentScoring(experimentId);
  const metricsSets = metricsSetsQuery.data ?? [];
  const [overrideSetId, setOverrideSetId] = useState("");
  const [saveAsDefault, setSaveAsDefault] = useState(false);

  useEffect(() => {
    if (!open) {
      setOverrideSetId("");
      setSaveAsDefault(false);
      return;
    }
    if (!overrideSetId && metricsSets.length > 0) {
      setOverrideSetId(metricsSets[0].id);
    }
  }, [open, metricsSets, overrideSetId]);

  const overrideScore = useMutation({
    mutationFn: () =>
      evaluatePack(
        experimentId,
        evaluatePackBody({ overrideSetId, saveAsDefault }),
      ),
    onSuccess: async (data) => {
      await invalidate();
      toastEvaluateOutcome(data, {
        success: "Metrics pack scoring complete",
        withErrors: "Metrics pack scoring finished with errors",
      });
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
    },
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!overrideSetId) return;
    overrideScore.mutate();
  }

  const pending = scoringPending || overrideScore.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Score with another metrics set</DialogTitle>
            <DialogDescription>
              Run the metrics pack using a different set for this scoring run.
              Optionally pin that set as this experiment&apos;s default.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            {metricsSetsQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading metrics sets…</p>
            ) : metricsSets.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No metrics sets in this project yet.
              </p>
            ) : (
              <>
                <div className="flex flex-col gap-2">
                  <label
                    htmlFor="score-override-metrics-set"
                    className="text-sm font-medium"
                  >
                    Metrics set
                  </label>
                  <Select
                    value={overrideSetId}
                    onValueChange={(v) => setOverrideSetId(v ?? "")}
                  >
                    <SelectTrigger id="score-override-metrics-set">
                      <SelectValue placeholder="Select metrics set" />
                    </SelectTrigger>
                    <SelectContent>
                      {metricsSets.map((s) => (
                        <SelectItem key={s.id} value={s.id}>
                          {s.name} v{s.version}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-2 hover:bg-surface">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 rounded border-border"
                    checked={saveAsDefault}
                    onChange={(e) => setSaveAsDefault(e.target.checked)}
                  />
                  <span className="text-sm text-foreground">
                    Salva come default di questo esperimento
                  </span>
                </label>
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
              disabled={
                pending || metricsSets.length === 0 || !overrideSetId
              }
            >
              {overrideScore.isPending ? "Scoring…" : "Score"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RunItemsSection({
  projectId,
  runId,
  evaluatorName,
  runStatus,
  itemsLoading,
  itemsError,
  onRetryItems,
  runItems,
  itemColumns,
  selectedItemIndex,
  onSelectedItemIndexChange,
}: {
  projectId: string;
  runId: string | null;
  evaluatorName: string | null;
  runStatus?: string;
  itemsLoading: boolean;
  itemsError: unknown;
  onRetryItems: () => void;
  runItems: RunItemView[];
  itemColumns: DataTableColumn<RunItemView>[];
  selectedItemIndex: number;
  onSelectedItemIndexChange: (index: number) => void;
}) {
  const selectedItemIndexClamped = Math.min(
    selectedItemIndex,
    Math.max(runItems.length - 1, 0),
  );
  const selectedItem = runItems[selectedItemIndexClamped] ?? null;
  const caseNumber =
    selectedItem && runItems.length > 0 ? selectedItemIndexClamped + 1 : null;

  return (
    <section className="flex flex-col gap-3 border-t border-border pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-foreground">Run items</h2>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {runId ? (
            <>
              <span>
                Evaluator{" "}
                <span className="font-medium text-foreground">
                  {evaluatorName ?? "—"}
                </span>
              </span>
              {runStatus ? <StatusBadge status={runStatus} /> : null}
              <CopyTechnicalId id={runId} label="Copy run ID" />
            </>
          ) : (
            <span>
              Not scored yet — questions and bound answers from this run.
            </span>
          )}
        </div>
      </div>

      {itemsLoading ? (
        <LoadingBlock className="min-h-[160px]" />
      ) : itemsError ? (
        <ErrorState
          title="Could not load run items"
          message={formatErrorForUi(itemsError)}
          onRetry={onRetryItems}
        />
      ) : runItems.length === 0 ? (
        <EmptyState
          title="No dataset items"
          description="This experiment's dataset has no cases to score."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <DataTable
            rows={runItems}
            columns={itemColumns}
            getRowKey={(row) => row.datasetItemId}
            selectedIndex={Math.min(
              selectedItemIndex,
              Math.max(runItems.length - 1, 0),
            )}
            onSelectedIndexChange={onSelectedItemIndexChange}
            onRowActivate={() => {}}
            aria-label="Evaluation run items"
          />
          {selectedItem ? (
            <ScrollArea className="max-h-[min(70vh,640px)] rounded-md border border-border p-4">
              <div className="flex flex-col gap-4 pr-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">
                    Case {caseNumber} of {runItems.length}
                  </span>
                  <CopyTechnicalId
                    id={selectedItem.datasetItemId}
                    label="Copy case ID"
                  />
                </div>
                <DetailBlock title="Question">
                  {formatJson(selectedItem.question)}
                </DetailBlock>
                <DetailBlock title="Expected answer">
                  {formatJson(selectedItem.expectedAnswer)}
                </DetailBlock>
                <DetailBlock title="Expected doc IDs">
                  {selectedItem.expectedDocIds.length > 0
                    ? selectedItem.expectedDocIds.join(", ")
                    : "—"}
                </DetailBlock>
                <DetailBlock title="Retrieved documents">
                  {selectedItem.retrievedDocuments != null
                    ? Array.isArray(selectedItem.retrievedDocuments) &&
                      selectedItem.retrievedDocuments.length === 0
                      ? "None (empty retrieval)"
                      : formatJson(selectedItem.retrievedDocuments)
                    : "—"}
                </DetailBlock>
                <DetailBlock title="Run context">
                  {selectedItem.context != null
                    ? formatJson(runContextWithoutDocuments(selectedItem.context))
                    : "—"}
                </DetailBlock>
                <DetailBlock title="Actual output">
                  {formatJson(selectedItem.actualOutput)}
                </DetailBlock>
                <DetailBlock title="Scores">
                  {formatScore(selectedItem.score)}
                  {selectedItem.label ? ` · ${selectedItem.label}` : ""}
                  {selectedItem.explanation?.trim()
                    ? `\n\n${selectedItem.explanation.trim()}`
                    : ""}
                </DetailBlock>
                {selectedItem.sourceTraceId ? (
                  <RunItemTimeline
                    projectId={projectId}
                    traceId={selectedItem.sourceTraceId}
                  />
                ) : null}
              </div>
            </ScrollArea>
          ) : null}
        </div>
      )}
    </section>
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
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({
        queryKey: experimentSummaryQueryKey(experimentId),
      });
      await queryClient.invalidateQueries({
        queryKey: experimentQueryOptions(experimentId).queryKey,
      });
      await queryClient.invalidateQueries({
        queryKey: experimentOutputsQueryKey(experimentId),
      });
      toastEvaluateOutcome(data, {
        success: "Evaluation complete",
        withErrors: "Evaluation finished with errors",
      });
      setSelectedIds(new Set());
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
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

  function handleSubmit(e: SubmitEvent) {
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
                ? ` Recommended for RAG Q&A: ${recommendedKinds.join(", ")}.`
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
