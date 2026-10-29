"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { CompareItemsTable } from "@/features/experiments/compare-items-table";
import { CompareTable } from "@/features/experiments/compare-table";
import {
  defaultCompareEvaluatorId,
  groupMetricsByEvaluator,
} from "@/features/experiments/group-metrics-by-evaluator";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/cn";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { runJudgeWarning } from "@/features/judges/judge-metadata";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import type { CompareRunRef, Experiment } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import {
  experimentCompareQueryOptions,
  useExperiment,
  useExperimentCompare,
  useExperiments,
} from "./use-experiments";
import { CommitLabel } from "./commit-label";
import {
  codeChange,
  experimentCommit,
  experimentModel,
  experimentVersion,
} from "./experiment-meta";

function judgeWarningsFromRuns(runs: CompareRunRef[] | undefined): string[] {
  if (!runs?.length) return [];
  const messages: string[] = [];
  for (const run of runs) {
    const message = runJudgeWarning(run.metadata);
    if (message) messages.push(message);
  }
  return messages;
}

type ExperimentCompareViewProps = {
  projectId: string;
  experimentId: string;
};

export function ExperimentCompareView({
  projectId,
  experimentId,
}: ExperimentCompareViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const baselineFromQuery = searchParams.get("baseline");

  const experimentQuery = useExperiment(experimentId);
  const experimentsQuery = useExperiments(projectId);
  const experiment = experimentQuery.data;

  const baselineCandidates = useMemo(() => {
    return (experimentsQuery.data ?? []).filter(
      (exp) => exp.id !== experimentId,
    );
  }, [experimentsQuery.data, experimentId]);

  const baselineId =
    baselineFromQuery?.trim() ||
    experiment?.baseline_experiment_id ||
    null;

  const baselineExperiment = useMemo(() => {
    if (!baselineId) return null;
    return (
      baselineCandidates.find((e) => e.id === baselineId) ??
      (experimentsQuery.data ?? []).find((e) => e.id === baselineId) ??
      null
    );
  }, [baselineCandidates, baselineId, experimentsQuery.data]);

  const compareQuery = useExperimentCompare(experimentId, baselineId);
  const [pickedEvaluatorId, setPickedEvaluatorId] = useState<string | null>(null);
  const compareOpts =
    baselineId != null
      ? experimentCompareQueryOptions(experimentId, baselineId)
      : null;

  function setBaselineId(id: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("baseline", id);
    params.set("project", projectId);
    router.replace(`${pathname}?${params.toString()}`);
  }

  if (experimentQuery.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (experimentQuery.isError) {
    const err = experimentQuery.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load experiment"
        message={message}
        onRetry={() => experimentQuery.refetch()}
      />
    );
  }

  if (!experiment) {
    return null;
  }

  const detailHref = withProjectQuery(
    `/experiments/${encodeURIComponent(experimentId)}`,
    projectId,
  );

  const baselinePicker = (
    <BaselineSelect
      candidates={baselineCandidates}
      value={baselineId}
      onValueChange={setBaselineId}
      loading={experimentsQuery.isLoading}
    />
  );

  if (!baselineId) {
    return (
      <div className="flex flex-col gap-3">
        <CompareHeader
          experiment={experiment}
          detailHref={detailHref}
          baselineExperiment={null}
          baselinePicker={baselinePicker}
        />
        <EmptyState
          title="Choose a baseline"
          description="Pick an earlier experiment on the same test set. You'll see which metrics and which answers got better or worse."
        />
      </div>
    );
  }

  if (compareQuery.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <CompareHeader
          experiment={experiment}
          detailHref={detailHref}
          baselineExperiment={baselineExperiment}
          baselinePicker={baselinePicker}
        />
        <LoadingBlock className="min-h-[200px]" />
      </div>
    );
  }

  if (compareQuery.isError) {
    const err = compareQuery.error;
    const rawMessage = formatErrorForUi(err);
    const isDatasetMismatch =
      err instanceof ApiError &&
      err.status === 400 &&
      rawMessage.includes(
        "Runs must share the same dataset (test set version)",
      );
    const message = isDatasetMismatch
      ? "Both experiments must use the same test set version. Pick a baseline that ran on the same test set."
      : rawMessage;
    return (
      <div className="flex flex-col gap-3">
        <CompareHeader
          experiment={experiment}
          detailHref={detailHref}
          baselineExperiment={baselineExperiment}
          baselinePicker={baselinePicker}
        />
        <ErrorState
          title={
            isDatasetMismatch ? "Different test sets" : "Could not compare experiments"
          }
          message={message}
          onRetry={() => compareQuery.refetch()}
        />
      </div>
    );
  }

  const comparison = compareQuery.data;
  const candidateJudgeWarnings = judgeWarningsFromRuns(comparison?.candidate_runs);
  const baselineJudgeWarnings = judgeWarningsFromRuns(comparison?.baseline_runs);
  const judgeWarningTitle = [...candidateJudgeWarnings, ...baselineJudgeWarnings].join(
    "\n",
  );
  const hasJudgeUnsuitable =
    candidateJudgeWarnings.length > 0 || baselineJudgeWarnings.length > 0;

  // Count per evaluator row, with the same verdict the table shows (worse of
  // mean score / pass rate), so the banner and the rows always agree.
  const evaluatorRows = groupMetricsByEvaluator(comparison?.metrics ?? []);
  const selectedEvaluatorId =
    pickedEvaluatorId && evaluatorRows.some((r) => r.evaluator_id === pickedEvaluatorId)
      ? pickedEvaluatorId
      : defaultCompareEvaluatorId(evaluatorRows);
  const verdicts = evaluatorRows.map((r) => r.status);
  const nWorse = verdicts.filter((s) => s === "regression").length;
  const nBetter = verdicts.filter((s) => s === "improved").length;
  const nUnchanged = verdicts.filter((s) => s === "unchanged").length;
  const notComparable = verdicts.length - nWorse - nBetter - nUnchanged;

  return (
    <div className="flex flex-col gap-5">
      <CompareHeader
        experiment={experiment}
        detailHref={detailHref}
        baselineExperiment={baselineExperiment}
        baselinePicker={baselinePicker}
        refresh={
          compareOpts ? (
            <RefreshControl
              queryKey={compareOpts.queryKey}
              dataUpdatedAt={compareQuery.dataUpdatedAt}
            />
          ) : null
        }
      />
      {comparison ? (
        <>
          <div
            role="status"
            className={cn(
              "flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border px-4 py-3",
              nWorse > 0
                ? "border-status-fail/40 bg-status-fail-bg"
                : "border-status-ok/40 bg-status-ok-bg",
            )}
          >
            <span
              className={cn(
                "text-sm font-semibold",
                nWorse > 0 ? "text-status-fail" : "text-status-ok",
              )}
            >
              {nWorse > 0
                ? `${nWorse} metric${nWorse === 1 ? "" : "s"} got worse`
                : nBetter > 0
                  ? "No metric got worse — some improved"
                  : "No metric got worse"}
            </span>
            <span className="text-sm text-foreground">
              {nBetter} better · {nWorse} worse ·{" "}
              {nUnchanged} no real change
            </span>
            {notComparable > 0 ? (
              <span
                className="text-sm text-status-warn"
                title="Some metrics were not scored on both experiments, were scored with different settings, or have too few answers to compare."
              >
                {notComparable} not comparable
              </span>
            ) : null}
            {hasJudgeUnsuitable ? (
              <Badge
                variant="outline"
                className="border-status-warn text-status-warn"
                title={judgeWarningTitle || "Judge model unsuitable"}
              >
                Judge results may be unreliable
              </Badge>
            ) : null}
          </div>
          <CompareTable
            metrics={comparison.metrics}
            selectedEvaluatorId={selectedEvaluatorId}
            onSelectEvaluator={setPickedEvaluatorId}
          />
          <CompareItemsTable
            projectId={projectId}
            experimentId={experimentId}
            baselineId={baselineId}
            metrics={comparison.metrics}
            candidateName={experiment.name}
            baselineName={baselineExperiment?.name}
            evaluatorId={selectedEvaluatorId}
          />
        </>
      ) : null}
    </div>
  );
}
function BaselineSelect({
  candidates,
  value,
  onValueChange,
  loading,
}: {
  candidates: Experiment[];
  value: string | null;
  onValueChange: (id: string) => void;
  loading: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="compare-baseline" id="compare-baseline-label" className="sr-only">
        Baseline experiment
      </label>
      <Select
        value={value ?? ""}
        onValueChange={(v) => {
          if (v) onValueChange(v);
        }}
        disabled={loading || candidates.length === 0}
      >
        <SelectTrigger id="compare-baseline" className="w-full">
          <SelectValue
            placeholder={
              loading
                ? "Loading experiments…"
                : candidates.length === 0
                  ? "No other experiments yet"
                  : "Choose the experiment to compare against"
            }
          />
        </SelectTrigger>
        <SelectContent>
          {candidates.map((exp) => (
            <SelectItem key={exp.id} value={exp.id}>
              {exp.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function ExperimentMetaLine({ experiment }: { experiment: Experiment }) {
  const model = experimentModel(experiment);
  const version = experimentVersion(experiment);
  const commit = experimentCommit(experiment);
  const parts = [
    model ? `Model ${model}` : null,
    version && version !== experiment.name ? `Version ${version}` : null,
  ].filter(Boolean);
  if (parts.length === 0 && !commit) return null;
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      {parts.length > 0 ? <span>{parts.join(" · ")}</span> : null}
      {commit ? <CommitLabel commit={commit} /> : <span>Commit not recorded</span>}
    </span>
  );
}

function CodeChangeNote({
  baseline,
  candidate,
}: {
  baseline: Experiment;
  candidate: Experiment;
}) {
  const change = codeChange(baseline.git, candidate.git);
  if (change.kind === "unknown") return null;
  if (change.kind === "same") {
    return (
      <p className="text-xs text-status-warn">
        Both experiments ran the same commit
        {change.dirty ? " (with uncommitted changes)" : ""}: differences come from
        config, model or data, not from committed code.
      </p>
    );
  }
  if (!change.diffHref) return null;
  return (
    <a
      href={change.diffHref}
      target="_blank"
      rel="noreferrer"
      className="self-start text-xs text-primary hover:underline"
    >
      View code changes between baseline and candidate
    </a>
  );
}

function CompareHeader({
  experiment,
  detailHref,
  baselineExperiment,
  baselinePicker,
  refresh,
}: {
  experiment: Experiment;
  detailHref: string;
  baselineExperiment: Experiment | null;
  baselinePicker: ReactNode;
  refresh?: ReactNode;
}) {
  const listHref = detailHref.replace(/\/experiments\/[^?]+/, "/experiments");
  return (
    <>
      <PageHeader
        breadcrumbs={[
          { label: "Experiments", href: listHref },
          { label: experiment.name, href: detailHref },
          { label: "Compare" },
        ]}
        title="Compare experiments"
        description="See what got better or worse between a baseline and a candidate on the same test set."
        actions={refresh}
        className="mb-0"
      />
      <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-stretch">
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
          <span className="text-[13px] font-medium text-muted-foreground">
            Baseline
          </span>
          {baselinePicker}
          {baselineExperiment ? <ExperimentMetaLine experiment={baselineExperiment} /> : null}
        </div>
        <div className="hidden items-center justify-center text-muted-foreground md:flex">
          <ArrowRight className="size-5" />
        </div>
        <div className="flex flex-col gap-2 rounded-lg border border-primary/40 bg-surface p-4">
          <span className="text-[13px] font-medium text-primary">
            Candidate
          </span>
          <Link href={detailHref} className="text-sm font-medium text-foreground hover:underline">
            {experiment.name}
          </Link>
          <ExperimentMetaLine experiment={experiment} />
        </div>
      </div>
      {baselineExperiment ? (
        <CodeChangeNote baseline={baselineExperiment} candidate={experiment} />
      ) : null}
    </>
  );
}
