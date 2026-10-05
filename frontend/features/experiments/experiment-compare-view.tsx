"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { ArrowLeft } from "lucide-react";
import { CompareItemsTable } from "@/features/experiments/compare-items-table";
import { CompareTable } from "@/features/experiments/compare-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import type { Experiment } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import {
  experimentCompareQueryOptions,
  useExperiment,
  useExperimentCompare,
  useExperiments,
} from "./use-experiments";
import { experimentModel, experimentVersion } from "./experiment-meta";

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
          description="Pick another experiment on the same test set to compare against. You'll see deltas on metrics both runs share."
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
    const rawMessage =
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : "Unknown error";
    const isDatasetMismatch =
      err instanceof ApiError &&
      err.status === 400 &&
      rawMessage.includes(
        "Runs must share the same dataset (test set version)",
      );
    const message = isDatasetMismatch
      ? "Runs must share the same dataset (test set version). Choose a baseline experiment created on the same dataset."
      : err instanceof ApiError
        ? `${err.status}: ${rawMessage}`
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
  const unavailableCount =
    comparison?.metrics.filter((m) => m.status === "unavailable").length ?? 0;

  return (
    <div className="flex flex-col gap-3">
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
          <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
            <span>
              Regressions{" "}
              <span className="font-mono tabular-nums text-status-fail">
                {comparison.regressions.length}
              </span>
            </span>
            <span>
              Improved{" "}
              <span className="font-mono tabular-nums text-status-ok">
                {comparison.improved.length}
              </span>
            </span>
            <span>
              Unchanged{" "}
              <span className="font-mono tabular-nums text-foreground">
                {comparison.unchanged.length}
              </span>
            </span>
            <span>
              Unavailable{" "}
              <span className="font-mono tabular-nums text-status-warn">
                {unavailableCount}
              </span>
            </span>
          </div>
          <CompareTable metrics={comparison.metrics} />
          <CompareItemsTable
            projectId={projectId}
            experimentId={experimentId}
            baselineId={baselineId}
            metrics={comparison.metrics}
            candidateName={experiment.name}
            baselineName={baselineExperiment?.name}
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
    <div className="flex flex-col gap-1 sm:min-w-[220px]">
      <label htmlFor="compare-baseline" className="text-xs font-medium text-muted-foreground">
        Baseline
      </label>
      <Select
        value={value ?? ""}
        onValueChange={(v) => {
          if (v) onValueChange(v);
        }}
        disabled={loading || candidates.length === 0}
      >
        <SelectTrigger id="compare-baseline" className="w-full sm:w-[260px]">
          <SelectValue
            placeholder={
              loading
                ? "Loading experiments…"
                : candidates.length === 0
                  ? "No other experiments"
                  : "Select baseline"
            }
          />
        </SelectTrigger>
        <SelectContent>
          {candidates.map((exp) => (
            <SelectItem key={exp.id} value={exp.id}>
              <span className="flex flex-col items-start gap-0.5">
                <span>{exp.name}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {truncateId(exp.id, 12)}
                </span>
              </span>
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
  const parts = [
    model ? `Model ${model}` : null,
    version ? `Version ${version}` : null,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <span className="text-muted-foreground">{parts.join(" · ")}</span>;
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
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<Link href={detailHref} />}
          >
            <ArrowLeft className="size-4" />
            Back
          </Button>
          <h1 className="text-lg font-semibold text-foreground">
            Compare · {experiment.name}
          </h1>
        </div>
        <p className="text-sm text-muted-foreground">
          Candidate{" "}
          <span className="font-medium text-foreground">{experiment.name}</span>
          {experimentModel(experiment) || experimentVersion(experiment)
            ? " · "
            : null}
          <ExperimentMetaLine experiment={experiment} />
        </p>
        <div className="flex flex-wrap items-end gap-4">
          {baselinePicker}
          {baselineExperiment ? (
            <p className="text-sm text-muted-foreground">
              Comparing to{" "}
              <span className="font-medium text-foreground">
                {baselineExperiment.name}
              </span>
              {experimentModel(baselineExperiment) ||
              experimentVersion(baselineExperiment)
                ? " · "
                : null}
              <ExperimentMetaLine experiment={baselineExperiment} />{" "}
              <span className="font-mono text-xs">
                {truncateId(baselineExperiment.id, 12)}
              </span>
            </p>
          ) : null}
        </div>
      </div>
      {refresh}
    </div>
  );
}
