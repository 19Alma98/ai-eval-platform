"use client";

import Link from "next/link";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type SubmitEvent } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, GitCompare, Play, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { formatConfigValue } from "@/features/app-configs/format-config-value";
import { RAG_RECOMMENDED_EVALUATOR_KINDS } from "@/features/datasets/rag-qa";
import { useDatasets, useDataset } from "@/features/datasets/use-datasets";
import { CreateEvaluatorDialog } from "./create-evaluator-dialog";
import { withProjectQuery } from "@/lib/project-href";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetaItem, PageHeader } from "@/components/page-header";
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
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatErrorForUi } from "@/lib/api/client";
import { evaluateExperiment, evaluatePack } from "@/lib/api/experiments";
import type { EvaluationRun } from "@/lib/api/types";
import { toastEvaluateOutcome } from "@/features/experiments/evaluate-outcome";
import { evaluatePackBody } from "@/features/metrics/metrics-set-submit";
import {
  useMetricsSet,
  useMetricsSets,
} from "@/features/metrics/use-metrics-sets";
import { runJudgeWarning } from "@/features/judges/judge-metadata";
import { cn } from "@/lib/cn";
import { resolveLabel } from "@/lib/format";
import { metricInfo, metricLabel, metricsSetDisplayName } from "@/lib/metrics-catalog";
import { projectsQueryOptions } from "@/lib/queries/projects";
import {
  evaluationRunQueryKey,
  evaluationRunQueryOptions,
  experimentQueryKey,
  experimentQueryOptions,
  experimentOutputsQueryKey,
  experimentSummaryQueryKey,
  experimentSummaryQueryOptions,
  useEvaluators,
  useExperiment,
  useExperimentOutputs,
  useExperimentSummary,
  useExperiments,
} from "./use-experiments";
import { buildCaseViews, type CaseView } from "./case-results";
import { flattenParams } from "./experiment-matrix";
import { CaseDetail } from "./case-detail";
import { ConnectAppCard } from "./connect-app-card";
import { MetricScorecard } from "./metric-scorecard";
import { CommitLabel } from "./commit-label";
import {
  experimentAppConfigChip,
  experimentAppConfigSnapshot,
  experimentCommit,
  experimentModel,
  experimentVersion,
  metricsSetBoundLabel,
  runMetricEntries,
} from "./experiment-meta";
import { tallyTargets } from "./metric-target";

function evaluatorKind(ev: { config: Record<string, unknown> }): string | null {
  const kind = ev.config?.kind;
  return typeof kind === "string" && kind.trim() ? kind.trim() : null;
}

function textOf(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

type CaseFilter = "all" | "failing" | "passing";

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
  const experimentsQuery = useExperiments(projectId);
  const projectsQuery = useQuery(projectsQueryOptions());
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
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [createEvaluatorOpen, setCreateEvaluatorOpen] = useState(false);
  const [focusedRunId, setFocusedRunId] = useState<string | null>(null);
  const [caseFilter, setCaseFilter] = useState<CaseFilter>("all");
  const [search, setSearch] = useState("");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // The selected answer lives in ?item= so every answer has a shareable URL.
  const [selectedItemId, setSelectedItemId] = useState<string | null>(() =>
    searchParams.get("item"),
  );
  const selectCase = useCallback(
    (itemId: string | null) => {
      setSelectedItemId(itemId);
      const params = new URLSearchParams(searchParams.toString());
      if (itemId) params.set("item", itemId);
      else params.delete("item");
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const experiment = experimentQuery.data;
  const evaluators = useMemo(
    () => summaryQuery.data?.evaluators ?? [],
    [summaryQuery.data?.evaluators],
  );
  const outputsQuery = useExperimentOutputs(experimentId);
  const datasetDetailQuery = useDataset(experiment?.dataset_id ?? null);

  const runQueries = useQueries({
    queries: evaluators.map((ev) => ({
      ...evaluationRunQueryOptions(ev.run_id),
      enabled: Boolean(ev.run_id),
    })),
  });
  const runsById = useMemo(() => {
    const map = new Map<string, EvaluationRun>();
    for (const q of runQueries) {
      if (q.data) map.set(q.data.id, q.data);
    }
    return map;
  }, [runQueries]);
  const runsLoading = runQueries.some((q) => q.isLoading);
  const judgeWarning = useMemo(() => {
    for (const run of runsById.values()) {
      const warning = runJudgeWarning(run.metadata);
      if (warning) return warning;
    }
    return null;
  }, [runsById]);

  const cases = useMemo(
    () =>
      buildCaseViews(
        datasetDetailQuery.data?.items ?? [],
        outputsQuery.data ?? [],
        evaluators,
        runsById,
      ),
    [datasetDetailQuery.data?.items, outputsQuery.data, evaluators, runsById],
  );

  const visibleCases = useMemo(() => {
    const q = search.trim().toLowerCase();
    return cases
      .map((c, index) => ({ c, index }))
      .filter(({ c }) => {
        if (q && !textOf(c.question).toLowerCase().includes(q)) return false;
        const relevant = focusedRunId
          ? c.results.filter((r) => r.metric.runId === focusedRunId)
          : c.results;
        const failing = relevant.some((r) => r.outcome === "fail" || r.outcome === "error");
        if (caseFilter === "failing") return failing;
        if (caseFilter === "passing") return !failing && relevant.some((r) => r.outcome === "pass");
        return true;
      });
  }, [cases, caseFilter, focusedRunId, search]);

  const nFailingCases = cases.filter((c) => c.failed.length > 0).length;
  const nAnswered = (outputsQuery.data ?? []).length;
  const scored = evaluators.length > 0;

  const scorePack = useScorePack(experimentId);

  // Only the experiment status is polled while it runs; when a run finishes
  // (or the user hits Refresh) pull the scores and answers it produced too.
  const queryClient = useQueryClient();
  const refreshAll = useCallback(
    () =>
      Promise.all([
        queryClient.refetchQueries({ queryKey: experimentQueryKey(experimentId) }),
        queryClient.refetchQueries({ queryKey: experimentSummaryQueryKey(experimentId) }),
        queryClient.refetchQueries({ queryKey: experimentOutputsQueryKey(experimentId) }),
        queryClient.invalidateQueries({ queryKey: evaluationRunQueryKey("").slice(0, 1) }),
      ]),
    [experimentId, queryClient],
  );
  const status = experiment?.status?.toLowerCase();
  const prevStatus = useRef(status);
  useEffect(() => {
    if (prevStatus.current === "running" && status !== "running") void refreshAll();
    prevStatus.current = status;
  }, [refreshAll, status]);

  const caseColumns: DataTableColumn<{ c: CaseView; index: number }>[] = useMemo(
    () => [
      {
        id: "index",
        header: "#",
        headerClassName: "w-[44px]",
        className: "tabular-nums text-muted-foreground",
        cell: (row) => row.index + 1,
      },
      {
        id: "question",
        header: "Question",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-foreground">{textOf(row.c.question)}</span>
        ),
      },
      {
        id: "result",
        header: "Result",
        headerClassName: "w-[220px]",
        wrap: true,
        cell: (row) => <CaseResultCell item={row.c} focusedRunId={focusedRunId} />,
      },
    ],
    [focusedRunId],
  );

  const isLoading = experimentQuery.isLoading || summaryQuery.isLoading;
  const isError = experimentQuery.isError || summaryQuery.isError;

  if (isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (isError) {
    const err = experimentQuery.error ?? summaryQuery.error;
    return (
      <ErrorState
        title="Could not load experiment"
        message={formatErrorForUi(err)}
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

  const listHref = withProjectQuery("/experiments", projectId);
  const dataset = (datasetsQuery.data ?? []).find((d) => d.id === experiment.dataset_id);
  const datasetLabel = dataset?.name?.trim() || "Deleted test set";
  const datasetHref = withProjectQuery(
    `/datasets/${encodeURIComponent(experiment.dataset_id)}`,
    projectId,
  );
  const experimentNames = new Map(
    (experimentsQuery.data ?? []).map((e) => [e.id, e.name] as const),
  );
  const baselineId = experiment.baseline_experiment_id;
  const otherExperiments = (experimentsQuery.data ?? []).filter(
    (e) => e.id !== experiment.id && e.dataset_id === experiment.dataset_id,
  );
  const compareHref = withProjectQuery(
    `/experiments/${encodeURIComponent(experimentId)}/compare${
      baselineId ? `?baseline=${encodeURIComponent(baselineId)}` : ""
    }`,
    projectId,
  );
  const releaseHref = withProjectQuery(
    `/release?experiment=${encodeURIComponent(experimentId)}`,
    projectId,
  );
  const modelLabel = experimentModel(experiment);
  const versionLabel = experimentVersion(experiment);
  const commit = experimentCommit(experiment);
  const appConfigChip = experimentAppConfigChip(experiment);
  const appConfigSnapshot = experimentAppConfigSnapshot(experiment);
  const metricsSetLabel = metricsSetBoundLabel(
    experiment,
    metricsSetsQuery.data,
    boundSetDetailQuery.data,
  );
  const projectSlug =
    (projectsQuery.data ?? []).find((p) => p.id === projectId)?.slug ?? null;
  const nQuestions = datasetDetailQuery.data?.items.length ?? 0;
  const itemsLoading = outputsQuery.isLoading || datasetDetailQuery.isLoading;
  const selectedCaseIndex = Math.max(
    0,
    visibleCases.findIndex((v) => v.c.datasetItemId === selectedItemId),
  );
  const selected = visibleCases[Math.min(selectedCaseIndex, Math.max(visibleCases.length - 1, 0))];
  const focusedMetric = focusedRunId
    ? evaluators.find((e) => e.run_id === focusedRunId)
    : undefined;
  const params = Object.entries(flattenParams(experiment.model_config ?? {})).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  // The model is already in the header; repeating it as a parameter is noise.
  const runDetails: [string, string][] = [
    ...runMetricEntries(summaryQuery.data?.experiment_metrics ?? {}),
    ...params.filter(([key, value]) => !(key === "model" && value === modelLabel)),
  ];
  const targets = tallyTargets(evaluators);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        breadcrumbs={[{ label: "Experiments", href: listHref }, { label: experiment.name }]}
        title={experiment.name}
        badges={<StatusBadge status={experiment.status} kind="experiment" />}
        meta={
          <>
            <MetaItem label="Test set">
              <Link href={datasetHref} className="hover:text-primary hover:underline">
                {datasetLabel}
              </Link>
            </MetaItem>
            {appConfigChip ? (
              <MetaItem label="App config">
                <Link
                  href={withProjectQuery(
                    `/app-configs/${encodeURIComponent(appConfigChip.familyName)}`,
                    projectId,
                  )}
                  className="hover:text-primary hover:underline"
                >
                  {appConfigChip.label}
                </Link>
              </MetaItem>
            ) : null}
            {modelLabel ? <MetaItem label="Model">{modelLabel}</MetaItem> : null}
            {versionLabel && versionLabel !== experiment.name ? (
              <MetaItem label="Version">{versionLabel}</MetaItem>
            ) : null}
            {commit ? (
              <MetaItem label="Commit">
                <CommitLabel commit={commit} />
              </MetaItem>
            ) : null}
            <MetaItem label="Metrics">{metricsSetLabel}</MetaItem>
            {baselineId ? (
              <MetaItem label="Baseline">
                <Link
                  href={withProjectQuery(`/experiments/${encodeURIComponent(baselineId)}`, projectId)}
                  className="hover:text-primary hover:underline"
                >
                  {resolveLabel(baselineId, experimentNames, "Earlier experiment")}
                </Link>
              </MetaItem>
            ) : null}
            <MetaItem label="Created">
              <RelativeTime date={experiment.created_at} />
            </MetaItem>
          </>
        }
        actions={
          <>
            <RefreshControl
              queryKey={summaryOpts.queryKey}
              dataUpdatedAt={summaryQuery.dataUpdatedAt}
              onRefresh={refreshAll}
            />
            {otherExperiments.length > 0 ? (
              <Button
                variant="outline"
                size="sm"
                nativeButton={false}
                render={<Link href={compareHref} />}
              >
                <GitCompare className="size-4" />
                Compare
              </Button>
            ) : null}
            {scored ? (
              <Button
                variant="outline"
                size="sm"
                nativeButton={false}
                render={<Link href={releaseHref} />}
              >
                <ShieldCheck className="size-4" />
                Quality gate
              </Button>
            ) : null}
            <div className="flex items-center">
              <Button
                type="button"
                size="sm"
                className="rounded-r-none"
                disabled={scorePack.isPending || nAnswered === 0}
                title={nAnswered === 0 ? "No answers to score yet" : undefined}
                onClick={() => scorePack.mutate()}
              >
                <Play className="size-4" />
                {scorePack.isPending ? "Scoring…" : scored ? "Re-score answers" : "Score answers"}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button
                      type="button"
                      size="sm"
                      className="rounded-l-none border-l border-primary-foreground/20 px-2"
                      aria-label="More scoring options"
                      disabled={scorePack.isPending}
                    />
                  }
                >
                  <ChevronDown className="size-4" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-[260px]">
                  <DropdownMenuItem onClick={() => setOverrideOpen(true)}>
                    Score with other metrics…
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setEvaluateOpen(true)}>
                    Run individual metrics…
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => setCreateEvaluatorOpen(true)}>
                    Create custom metric…
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </>
        }
        className="mb-0"
      />

      {judgeWarning ? (
        <div
          role="status"
          className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn"
        >
          <strong>Judge results may be unreliable.</strong> {judgeWarning}
        </div>
      ) : null}

      {!itemsLoading && nAnswered === 0 ? (
        <ConnectAppCard
          experimentId={experiment.id}
          datasetId={experiment.dataset_id}
          projectSlug={projectSlug}
          nQuestions={nQuestions}
        />
      ) : null}

      {scored ? (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-serif text-lg font-medium text-foreground">
              <span
                className={cn(
                  targets.missed > 0 ? "text-status-fail" : "text-status-ok",
                )}
              >
                {targets.met} of {targets.total}
              </span>{" "}
              metrics meet their target
            </h2>
            <p className="text-xs text-muted-foreground">
              Bars show the share of answers that pass each metric. Click a metric to see
              the answers that failed it.
            </p>
          </div>
          <MetricScorecard
            evaluators={evaluators}
            focusedRunId={focusedRunId}
            onFocus={(runId) => {
              setFocusedRunId(runId);
              setCaseFilter(runId ? "failing" : "all");
              selectCase(null);
            }}
          />
        </section>
      ) : nAnswered > 0 ? (
        <EmptyState
          title={`${nAnswered} answer${nAnswered === 1 ? "" : "s"} received — not scored yet`}
          description="Score the answers to see correctness, groundedness and retrieval quality for every question."
          action={
            <Button
              type="button"
              size="sm"
              disabled={scorePack.isPending}
              onClick={() => scorePack.mutate()}
            >
              <Play className="size-4" />
              {scorePack.isPending ? "Scoring…" : "Score answers"}
            </Button>
          }
        />
      ) : null}

      {runDetails.length > 0 ? <RunDetails entries={runDetails} /> : null}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 className="font-serif text-lg font-medium text-foreground">Answers</h2>
            {scored ? (
              <span className="text-sm text-muted-foreground">
                {nFailingCases === 0
                  ? "Every question passed all metrics"
                  : `${nFailingCases} of ${cases.length} questions fail at least one metric`}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {focusedMetric ? (
              <Badge variant="secondary" className="h-7 gap-1.5 px-2.5">
                Metric: {metricLabel(focusedMetric.evaluator_name)}
                <button
                  type="button"
                  aria-label="Clear metric filter"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setFocusedRunId(null);
                    setCaseFilter("all");
                  }}
                >
                  ×
                </button>
              </Badge>
            ) : null}
            {scored ? (
              <div role="radiogroup" aria-label="Filter answers" className="flex rounded-md border border-border bg-surface p-0.5">
                {(["all", "failing", "passing"] as const).map((key) => (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={caseFilter === key}
                    onClick={() => {
                      setCaseFilter(key);
                      selectCase(null);
                    }}
                    className={cn(
                      "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
                      caseFilter === key && "bg-row-selected text-foreground",
                    )}
                  >
                    {key === "all" ? "All" : key === "failing" ? "Failing" : "Passing"}
                  </button>
                ))}
              </div>
            ) : null}
            <Input
              type="search"
              placeholder="Search questions…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                selectCase(null);
              }}
              className="h-8 w-56"
              aria-label="Search questions"
            />
          </div>
        </div>

        {itemsLoading || (runsLoading && cases.length === 0) ? (
          <LoadingBlock className="min-h-[160px]" />
        ) : datasetDetailQuery.isError || outputsQuery.isError ? (
          <ErrorState
            title="Could not load answers"
            message={formatErrorForUi(datasetDetailQuery.error ?? outputsQuery.error)}
            onRetry={() => {
              void outputsQuery.refetch();
              void datasetDetailQuery.refetch();
            }}
          />
        ) : cases.length === 0 ? (
          <EmptyState
            title="The test set is empty"
            description="Add questions to the test set, then run your app on it."
          />
        ) : visibleCases.length === 0 ? (
          <EmptyState
            title="Nothing to show"
            description={
              caseFilter === "failing"
                ? "No answers fail with the current filter."
                : "No questions match your filters."
            }
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <DataTable
              rows={visibleCases}
              columns={caseColumns}
              getRowKey={(row) => row.c.datasetItemId}
              selectedIndex={Math.min(selectedCaseIndex, visibleCases.length - 1)}
              onSelectedIndexChange={(i) => selectCase(visibleCases[i]?.c.datasetItemId ?? null)}
              onRowActivate={() => {}}
              selectionMode="persistent"
              className="max-h-[min(75vh,760px)] self-start"
              aria-label="Answers"
            />
            {selected ? (
              <ScrollArea className="max-h-[min(75vh,760px)] rounded-lg border border-border bg-background p-4">
                <div className="pr-3">
                  <CaseDetail
                    projectId={projectId}
                    experimentId={experimentId}
                    item={selected.c}
                    position={selected.index + 1}
                    total={cases.length}
                  />
                </div>
              </ScrollArea>
            ) : null}
          </div>
        )}
      </section>

      {appConfigSnapshot ? (
        <details className="rounded-lg border border-border bg-surface px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            App configuration used
          </summary>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {(
              [
                ["Prompt", appConfigSnapshot.prompt],
                ["Model", appConfigSnapshot.model],
                ["Retrieval", appConfigSnapshot.retrieval],
              ] as const
            ).map(([title, value]) => (
              <div key={title} className="flex flex-col gap-1.5">
                <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
                <div className="max-h-[200px] overflow-auto rounded-md border border-border bg-background p-3 text-sm whitespace-pre-wrap break-words text-foreground">
                  {formatConfigValue(value)}
                </div>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      <ScorePackOverrideDialog
        projectId={projectId}
        experimentId={experimentId}
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        scoringPending={scorePack.isPending}
      />
      <EvaluateDialog
        projectId={projectId}
        experimentId={experimentId}
        recommendedKinds={[...RAG_RECOMMENDED_EVALUATOR_KINDS]}
        open={evaluateOpen}
        onOpenChange={setEvaluateOpen}
        onCreateEvaluator={() => {
          setEvaluateOpen(false);
          setCreateEvaluatorOpen(true);
        }}
      />
      <CreateEvaluatorDialog
        projectId={projectId}
        open={createEvaluatorOpen}
        onOpenChange={setCreateEvaluatorOpen}
      />
    </div>
  );
}

function CaseResultCell({
  item,
  focusedRunId,
}: {
  item: CaseView;
  focusedRunId: string | null;
}) {
  if (item.actualOutput === null || item.actualOutput === undefined) {
    return <span className="text-xs text-muted-foreground">No answer yet</span>;
  }
  if (item.nScored === 0) {
    return <span className="text-xs text-muted-foreground">Not scored</span>;
  }
  const focused = focusedRunId
    ? item.results.find((r) => r.metric.runId === focusedRunId)
    : null;
  if (focused) {
    return <StatusBadge status={focused.outcome} />;
  }
  if (item.failed.length === 0) {
    return (
      <span className="text-xs font-medium text-status-ok">
        All {item.nScored} passed
      </span>
    );
  }
  const shown = item.failed.slice(0, 2);
  const extra = item.failed.length - shown.length;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((r) => (
        <span
          key={r.metric.runId}
          className="rounded bg-status-fail-bg px-1.5 py-0.5 text-xs font-medium text-status-fail"
        >
          {r.metric.label}
        </span>
      ))}
      {extra > 0 ? (
        <span className="text-xs text-muted-foreground">+{extra}</span>
      ) : null}
    </span>
  );
}

function useScorePack(experimentId: string) {
  const invalidate = useInvalidateExperimentScoring(experimentId);
  return useMutation({
    mutationFn: () => evaluatePack(experimentId),
    onMutate: () => {
      toast.message("Scoring answers…", {
        description: "This can take a minute with LLM judges. The page updates when done.",
      });
    },
    onSuccess: async (data) => {
      await invalidate();
      toastEvaluateOutcome(data, {
        success: "Answers scored",
        withErrors: "Scoring finished with errors",
      });
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
    },
  });
}

function RunDetails({ entries }: { entries: [string, string][] }) {
  return (
    <section
      aria-label="Run details"
      className="flex flex-wrap items-center gap-x-6 gap-y-2 border-y border-border py-2.5 text-sm"
    >
      <h2 className="text-[13px] font-medium text-muted-foreground">
        Run details
      </h2>
      <dl className="flex flex-wrap items-center gap-x-5 gap-y-1">
        {entries.map(([key, value]) => (
          <div key={key} className="flex min-w-0 items-baseline gap-1.5">
            <dt className="truncate text-muted-foreground" title={key}>
              {key}
            </dt>
            <dd className="max-w-[240px] truncate font-medium tabular-nums text-foreground" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
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
  const metricsSets = useMemo(
    () => metricsSetsQuery.data ?? [],
    [metricsSetsQuery.data],
  );
  const [overrideSetId, setOverrideSetId] = useState("");
  const [saveAsDefault, setSaveAsDefault] = useState(false);

  const [prevDialogOpen, setPrevDialogOpen] = useState(open);
  if (open !== prevDialogOpen) {
    setPrevDialogOpen(open);
    if (!open) {
      setOverrideSetId("");
      setSaveAsDefault(false);
    }
  }
  if (open && !overrideSetId && metricsSets.length > 0) {
    setOverrideSetId(metricsSets[0].id);
  }

  const overrideScore = useMutation({
    mutationFn: () =>
      evaluatePack(
        experimentId,
        evaluatePackBody({ overrideSetId, saveAsDefault }),
      ),
    onSuccess: async (data) => {
      await invalidate();
      toastEvaluateOutcome(data, {
        success: "Answers scored",
        withErrors: "Scoring finished with errors",
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
            <DialogTitle>Score with other metrics</DialogTitle>
            <DialogDescription>
              Score this experiment&apos;s answers with a different metrics set,
              for example stricter thresholds.
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
                    Metrics
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
                          {metricsSetDisplayName(s.name)} · v{s.version}
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
                    Always use these metrics for this experiment
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
        success: "Answers scored",
        withErrors: "Scoring finished with errors",
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

  const evaluators = useMemo(
    () => evaluatorsQuery.data ?? [],
    [evaluatorsQuery.data],
  );
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
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Run individual metrics</DialogTitle>
            <DialogDescription>
              Score the answers with only the metrics you pick, for example to
              re-check one metric after changing its judge.
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[280px] flex-col gap-2 overflow-y-auto py-4">
            {evaluatorsQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading metrics…</p>
            ) : evaluators.length === 0 ? (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  No metrics in this project yet.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={onCreateEvaluator}
                >
                  Create metric
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
                    None of the recommended RAG metrics exist in this project yet.
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
                          {metricLabel(kind ?? ev.name)}
                          {isRecommended ? (
                            <Badge variant="secondary">Recommended</Badge>
                          ) : null}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {metricInfo(kind ?? ev.name).description || ev.name}
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
              {evaluate.isPending ? "Scoring…" : "Score with selected"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
