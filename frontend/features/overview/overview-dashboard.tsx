"use client";

import { useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { TimeRangePicker } from "@/components/time-range-picker";
import { RefreshControl } from "@/components/refresh-control";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { formatErrorForUi } from "@/lib/api/client";
import { useProjectId } from "@/lib/project-store";
import { rangeFromPreset, type Preset } from "@/lib/time-range";
import { cn } from "@/lib/cn";
import { parseOverviewRangeParam, OVERVIEW_DEFAULT_PRESET } from "./overview-range";
import { useOverview, overviewQueryKey } from "./use-overview";
import { DualKpi } from "./dual-kpi";
import { LiveQualityChart } from "./live-quality-chart";
import { CompareBars } from "./compare-bars";
import { AttentionQueue } from "./attention-queue";
import { LoopProgress } from "./loop-progress";
import {
  buildLoopCards,
  mapOverviewToDualKpi,
  mergeAttentionItems,
  overviewWarningMessages,
} from "./map-overview";

function OverviewSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md border border-border bg-surface-2", className)}
      aria-hidden
    />
  );
}

export function OverviewDashboard() {
  const { projectId } = useProjectId();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const preset = parseOverviewRangeParam(searchParams.get("range"));
  const { start, end } = useMemo(() => rangeFromPreset(preset), [preset]);
  const since = start.toISOString();
  const until = end.toISOString();
  const overviewQuery = useOverview(projectId, since, until);

  useEffect(() => {
    if (searchParams.get("range") != null) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("range", OVERVIEW_DEFAULT_PRESET);
    router.replace(`${pathname}?${params.toString()}`);
  }, [pathname, router, searchParams]);

  const setPreset = useCallback(
    (p: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("range", p);
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const widenRange = useCallback(() => {
    const order: Preset[] = ["15m", "1h", "6h", "24h", "7d"];
    const idx = order.indexOf(preset);
    const next = order[Math.min(idx + 1, order.length - 1)];
    setPreset(next);
  }, [preset, setPreset]);

  const onRefresh = useCallback(async () => {
    if (!projectId) return;
    await queryClient.refetchQueries({
      queryKey: overviewQueryKey(projectId, since, until),
    });
  }, [projectId, queryClient, since, until]);

  const overview = overviewQuery.data;
  const loading = overviewQuery.isLoading && !overview;
  const loadFailed = overviewQuery.isError && !overview;

  const dualKpi = overview ? mapOverviewToDualKpi(overview) : null;
  const loopCards = overview ? buildLoopCards(overview) : null;
  const attentionRows = overview ? mergeAttentionItems(overview) : [];
  const warningMessages = overview ? overviewWarningMessages(overview.warnings) : [];

  const setupIncomplete = loopCards?.some((c) => c.status === "empty") ?? false;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Overview"
        description="How your AI app is doing in production and how the next version scores before release."
        actions={
          <>
            <TimeRangePicker preset={preset} onPresetChange={setPreset} />
            {projectId ? (
              <RefreshControl
                dataUpdatedAt={overviewQuery.dataUpdatedAt}
                onRefresh={onRefresh}
              />
            ) : null}
          </>
        }
        className="mb-0"
      />

      {warningMessages.length > 0 ? (
        <div
          role="status"
          className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn"
        >
          {warningMessages.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      {loadFailed ? (
        <ErrorState
          title="Could not load overview"
          message={formatErrorForUi(overviewQuery.error)}
          onRetry={() => void overviewQuery.refetch()}
        />
      ) : null}

      <div
        aria-busy={loading}
        className={cn("flex flex-col gap-6", loading && "pointer-events-none opacity-90")}
      >
        {loadFailed ? null : loading || !projectId || !dualKpi ? (
          <>
            <OverviewSkeleton className="h-40" />
            <div className="grid gap-4 lg:grid-cols-2">
              <OverviewSkeleton className="h-64" />
              <OverviewSkeleton className="h-64" />
            </div>
          </>
        ) : overview ? (
          <>
            {setupIncomplete && loopCards ? (
              <section className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold text-foreground">Getting started</h2>
                <LoopProgress projectId={projectId} cards={loopCards} />
              </section>
            ) : null}

            <DualKpi projectId={projectId} model={dualKpi} />

            <div className="grid gap-4 lg:grid-cols-2">
              <AttentionQueue projectId={projectId} rows={attentionRows} />
              <CompareBars projectId={projectId} overview={overview} />
            </div>

            <LiveQualityChart
              projectId={projectId}
              series={overview.live.series}
              referenceThreshold={overview.offline.reference_threshold}
              onWidenRange={widenRange}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}
