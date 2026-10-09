"use client";

import { useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { TimeRangePicker } from "@/components/time-range-picker";
import { RefreshControl } from "@/components/refresh-control";
import { ErrorState } from "@/components/error-state";
import { PageIntro } from "@/components/page-intro";
import { RelativeTime } from "@/components/relative-time";
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

  return (
    <div className="flex flex-col gap-6">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-1 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <TimeRangePicker preset={preset} onPresetChange={setPreset} />
          {overview?.generated_at ? (
            <span className="text-xs text-muted-foreground">
              Snapshot{" "}
              <RelativeTime date={overview.generated_at} className="text-xs" />
            </span>
          ) : null}
        </div>
        {projectId ? (
          <RefreshControl
            dataUpdatedAt={overviewQuery.dataUpdatedAt}
            onRefresh={onRefresh}
          />
        ) : null}
      </div>

      <PageIntro
        title="Overview"
        glossary="Where you are in the quality loop — live signal and offline readiness in one place."
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
            <div className="grid gap-4 lg:grid-cols-2">
              <OverviewSkeleton className="h-48" />
              <OverviewSkeleton className="h-48" />
            </div>
          </>
        ) : overview ? (
          <>
            <DualKpi projectId={projectId} model={dualKpi} />

            <div className="grid gap-4 lg:grid-cols-2">
              <LiveQualityChart
                projectId={projectId}
                series={overview.live.series}
                referenceThreshold={overview.offline.reference_threshold}
                onWidenRange={widenRange}
              />
              <CompareBars projectId={projectId} overview={overview} />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <AttentionQueue projectId={projectId} rows={attentionRows} />
              <div className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold text-foreground">Quality loop</h2>
                {loopCards ? (
                  <LoopProgress projectId={projectId} cards={loopCards} />
                ) : null}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
