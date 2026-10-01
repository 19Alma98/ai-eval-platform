"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { CompareTable } from "@/features/experiments/compare-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { truncateId } from "@/lib/format";
import {
  experimentCompareQueryOptions,
  useExperiment,
  useExperimentCompare,
} from "./use-experiments";

type ExperimentCompareViewProps = {
  projectId: string;
  experimentId: string;
};

export function ExperimentCompareView({
  projectId,
  experimentId,
}: ExperimentCompareViewProps) {
  const searchParams = useSearchParams();
  const baselineFromQuery = searchParams.get("baseline");

  const experimentQuery = useExperiment(experimentId);
  const experiment = experimentQuery.data;

  const baselineId =
    baselineFromQuery?.trim() ||
    experiment?.baseline_experiment_id ||
    null;

  const compareQuery = useExperimentCompare(experimentId, baselineId);
  const compareOpts =
    baselineId != null
      ? experimentCompareQueryOptions(experimentId, baselineId)
      : null;

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

  const detailHref = `/experiments/${encodeURIComponent(experimentId)}?project=${encodeURIComponent(projectId)}`;

  if (!baselineId) {
    return (
      <div className="flex flex-col gap-3">
        <CompareHeader
          experimentName={experiment.name}
          detailHref={detailHref}
          baselineLabel={null}
        />
        <EmptyState
          title="Baseline required"
          description="Set baseline_experiment_id on the experiment or open this page with ?baseline=."
        />
      </div>
    );
  }

  if (compareQuery.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <CompareHeader
          experimentName={experiment.name}
          detailHref={detailHref}
          baselineLabel={truncateId(baselineId, 12)}
        />
        <LoadingBlock className="min-h-[200px]" />
      </div>
    );
  }

  if (compareQuery.isError) {
    const err = compareQuery.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <div className="flex flex-col gap-3">
        <CompareHeader
          experimentName={experiment.name}
          detailHref={detailHref}
          baselineLabel={truncateId(baselineId, 12)}
        />
        <ErrorState
          title="Could not compare experiments"
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
        experimentName={experiment.name}
        detailHref={detailHref}
        baselineLabel={truncateId(baselineId, 12)}
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
        </>
      ) : null}
    </div>
  );
}

function CompareHeader({
  experimentName,
  detailHref,
  baselineLabel,
  refresh,
}: {
  experimentName: string;
  detailHref: string;
  baselineLabel: string | null;
  refresh?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
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
            Compare · {experimentName}
          </h1>
        </div>
        {baselineLabel ? (
          <p className="text-sm text-muted-foreground">
            Baseline{" "}
            <span className="font-mono text-xs text-foreground">
              {baselineLabel}
            </span>
          </p>
        ) : null}
      </div>
      {refresh}
    </div>
  );
}
