"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useDeferredValue, useMemo, useState } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatErrorForUi } from "@/lib/api/client";
import type { TraceSummary } from "@/lib/api/types";
import { traceLabel } from "./trace-label";
import { cn } from "@/lib/cn";
import { formatDurationMs, formatScore } from "@/lib/format";
import { liveRunHref, traceHref } from "@/lib/links";
import { PRESETS, rangeFromPreset, type Preset } from "@/lib/time-range";
import { useTraces } from "./use-traces";

type StatusFilter = "all" | "error";
type RangeFilter = Preset | "all";

const RANGE_OPTIONS: RangeFilter[] = [...PRESETS, "all"];

function ScoreChips({ row }: { row: TraceSummary }) {
  if (row.scores.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {row.scores.slice(0, 4).map((s) => (
        <span
          key={s.id}
          className={cn(
            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs",
            s.label === "FAIL"
              ? "bg-status-fail-bg text-status-fail"
              : "bg-surface-2 text-foreground",
          )}
        >
          {s.name}
          {s.value != null ? (
            <span className="font-medium tabular-nums">{formatScore(s.value)}</span>
          ) : null}
        </span>
      ))}
      {row.scores.length > 4 ? (
        <span className="text-xs text-muted-foreground">+{row.scores.length - 4}</span>
      ) : null}
    </span>
  );
}

export function TraceList({ projectId }: { projectId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const status: StatusFilter = searchParams.get("status") === "error" ? "error" : "all";
  const rawRange = searchParams.get("range");
  const range: RangeFilter =
    rawRange && (RANGE_OPTIONS as string[]).includes(rawRange) ? (rawRange as RangeFilter) : "24h";
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const deferredSearch = useDeferredValue(search.trim());
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Recomputed only when the preset changes so the query key stays stable.
  const since = useMemo(
    () => (range === "all" ? undefined : rangeFromPreset(range).start.toISOString()),
    [range],
  );

  const query = useTraces(projectId, {
    status: status === "error" ? "error" : undefined,
    search: deferredSearch || undefined,
    since,
  });
  const rows = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const anyScores = rows.some((r) => r.scores.length > 0);
  const anyJudged = rows.some((r) => r.live_interaction_id);

  const setParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value == null) params.delete(key);
      else params.set(key, value);
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const onRowActivate = useCallback(
    (row: TraceSummary) => router.push(traceHref(projectId, row.trace_id)),
    [projectId, router],
  );

  const columns: DataTableColumn<TraceSummary>[] = useMemo(
    () => [
      {
        id: "start",
        header: "When",
        headerClassName: "w-[120px]",
        className: "text-muted-foreground",
        cell: (row) => <RelativeTime date={row.start_time} />,
      },
      {
        id: "name",
        header: "Trace",
        wrap: true,
        cell: (row) => {
          const label = traceLabel(row);
          return (
            <span className="flex min-w-0 flex-col">
              <span className="line-clamp-1 font-medium text-foreground">{label.title}</span>
              {label.subtitle ? (
                <span className="line-clamp-1 text-xs text-muted-foreground">
                  {label.subtitle}
                </span>
              ) : null}
            </span>
          );
        },
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[90px]",
        cell: (row) => <StatusBadge status={row.status} />,
      },
      {
        id: "duration",
        header: "Duration",
        headerClassName: "w-[100px]",
        className: "tabular-nums",
        cell: (row) => (row.duration_ms != null ? formatDurationMs(row.duration_ms) : "—"),
      },
      {
        id: "spans",
        header: "Steps",
        headerClassName: "w-[70px]",
        className: "tabular-nums",
        cell: (row) => String(row.span_count),
      },
      // Columns empty for every row are noise (see docs/07-frontend.md: tables stay lean).
      ...(anyScores
        ? [
            {
              id: "scores",
              header: "Scores",
              headerClassName: "w-[260px]",
              wrap: true,
              cell: (row: TraceSummary) => <ScoreChips row={row} />,
            },
          ]
        : []),
      ...(anyJudged
        ? [
            {
              id: "live",
              header: "Judged",
              headerClassName: "w-[90px]",
              cell: (row: TraceSummary) =>
                row.live_interaction_id ? (
                  <Link
                    href={liveRunHref(projectId, row.live_interaction_id)}
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs text-primary hover:underline"
                  >
                    Verdict
                  </Link>
                ) : (
                  <span className="text-muted-foreground">—</span>
                ),
            },
          ]
        : []),
    ],
    [anyJudged, anyScores, projectId],
  );

  const filtersActive = status !== "all" || deferredSearch !== "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div
          role="radiogroup"
          aria-label="Filter traces by status"
          className="flex rounded-md border border-border bg-surface p-0.5"
        >
          {(
            [
              ["all", "All"],
              ["error", "Errors"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={status === key}
              onClick={() => setParam("status", key === "all" ? null : key)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
                status === key && "bg-row-selected text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div
          role="radiogroup"
          aria-label="Time range"
          className="flex rounded-md border border-border bg-surface p-0.5"
        >
          {RANGE_OPTIONS.map((key) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={range === key}
              onClick={() => setParam("range", key)}
              className={cn(
                "rounded px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
                range === key && "bg-row-selected text-foreground",
              )}
            >
              {key === "all" ? "All time" : key}
            </button>
          ))}
        </div>
        <Input
          type="search"
          placeholder="Search name, trace, session or user ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 max-w-xs"
          aria-label="Search traces"
        />
      </div>

      {query.isLoading ? (
        <LoadingBlock />
      ) : query.isError ? (
        <ErrorState
          title="Could not load traces"
          message={formatErrorForUi(query.error)}
          onRetry={() => void query.refetch()}
        />
      ) : rows.length === 0 ? (
        filtersActive ? (
          <EmptyState
            title="Nothing matches"
            description="No traces match these filters. Clear the search or the status filter, or try a longer time range."
          />
        ) : (
          <EmptyState
            title={range === "all" ? "No traces yet" : "No traces in this time range"}
            description="Call `opengrade.init(project_slug=…)` once at startup and decorate your app's entry point with `@opengrade.trace` (or point any OpenTelemetry exporter at `/v1/traces`). Each call shows up here."
            action={
              range !== "all" ? (
                <Button type="button" variant="outline" size="sm" onClick={() => setParam("range", "all")}>
                  Show all time
                </Button>
              ) : null
            }
          />
        )
      ) : (
        <>
          <DataTable
            rows={rows}
            columns={columns}
            getRowKey={(row) => row.id}
            selectedIndex={selectedIndex}
            onSelectedIndexChange={setSelectedIndex}
            onRowActivate={onRowActivate}
            aria-label="Traces"
          />
          {query.hasNextPage ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="self-center"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? "Loading…" : "Load more"}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
