"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { formatErrorForUi } from "@/lib/api/client";
import type { TraceSummary } from "@/lib/api/types";
import { formatDurationMs } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useTimeRange } from "@/lib/time-range-context";
import { cn } from "@/lib/cn";
import {
  tracesQueryOptions,
  useTraces,
  type TracesFilters,
} from "./use-traces";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "ok", label: "OK" },
  { value: "error", label: "Error" },
  { value: "unset", label: "Unset" },
] as const;

function traceDurationMs(trace: TraceSummary): number | null {
  if (!trace.end_time) return null;
  return (
    new Date(trace.end_time).getTime() - new Date(trace.start_time).getTime()
  );
}

export function TraceList() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { projectId } = useProjectId();
  const { start, end } = useTimeRange();
  const statusFromUrl = searchParams.get("status") ?? "";
  const [statusFilter, setStatusFilter] = useState(statusFromUrl);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    setStatusFilter(statusFromUrl);
  }, [statusFromUrl]);

  const onStatusChange = useCallback(
    (value: string) => {
      setStatusFilter(value);
      setSelectedIndex(0);
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set("status", value);
      else params.delete("status");
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const filters: TracesFilters = useMemo(
    () => ({
      status: statusFilter || undefined,
      start: start.toISOString(),
      end: end.toISOString(),
      limit: 50,
    }),
    [statusFilter, start, end],
  );

  const query = useTraces(projectId, filters);
  const queryOpts = projectId
    ? tracesQueryOptions(projectId, filters)
    : null;

  const rows = query.data?.items ?? [];

  const onRowActivate = useCallback(
    (trace: TraceSummary) => {
      if (!projectId) return;
      router.push(
        `/traces/${encodeURIComponent(trace.trace_id)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<TraceSummary>[] = useMemo(
    () => [
      {
        id: "time",
        header: "Time",
        headerClassName: "w-[100px]",
        cell: (row) => <RelativeTime date={row.start_time} />,
      },
      {
        id: "name",
        header: "Name",
        cell: (row) => (
          <span className="font-medium text-foreground">{row.name}</span>
        ),
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[88px]",
        cell: (row) => <StatusBadge status={row.status} />,
      },
      {
        id: "spans",
        header: "Spans",
        headerClassName: "w-[64px] text-right",
        className: "text-right font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.span_count,
      },
      {
        id: "duration",
        header: "Duration",
        headerClassName: "w-[88px]",
        className: "font-mono tabular-nums text-muted-foreground",
        cell: (row) => {
          const ms = traceDurationMs(row);
          return ms == null ? "—" : formatDurationMs(ms);
        },
      },
    ],
    [],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load traces"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (rows.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <TraceListToolbar
          statusFilter={statusFilter}
          onStatusFilterChange={onStatusChange}
          queryOpts={queryOpts}
          dataUpdatedAt={query.dataUpdatedAt}
        />
        {statusFilter ? (
          <EmptyState
            title="No traces match this filter"
            description="Try another status or widen the time range."
          />
        ) : (
          <EmptyState
            title="No traces yet"
            description="Send telemetry to this project, then refresh. Developers can use OTLP (see examples/otlp_hello)."
            action={
              projectId ? (
                <Link
                  href={withProjectQuery("/overview", projectId)}
                  className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
                >
                  Back to Overview
                </Link>
              ) : null
            }
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <TraceListToolbar
        statusFilter={statusFilter}
        onStatusFilterChange={onStatusChange}
        queryOpts={queryOpts}
        dataUpdatedAt={query.dataUpdatedAt}
      />
      <DataTable
        rows={rows}
        columns={columns}
        getRowKey={(row) => row.trace_id}
        selectedIndex={selectedIndex}
        onSelectedIndexChange={setSelectedIndex}
        onRowActivate={onRowActivate}
        aria-label="Traces"
      />
    </div>
  );
}

function TraceListToolbar({
  statusFilter,
  onStatusFilterChange,
  queryOpts,
  dataUpdatedAt,
}: {
  statusFilter: string;
  onStatusFilterChange: (value: string) => void;
  queryOpts: ReturnType<typeof tracesQueryOptions> | null;
  dataUpdatedAt: number;
}) {
  return (
    <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center gap-3 border-b border-border bg-background px-1 pb-3">
      <div
        className="inline-flex rounded-md border border-border bg-surface p-0.5"
        role="group"
        aria-label="Filter by status"
      >
        {STATUS_FILTERS.map(({ value, label }) => (
          <button
            key={value || "all"}
            type="button"
            onClick={() => onStatusFilterChange(value)}
            aria-pressed={statusFilter === value}
            className={cn(
              "rounded px-2.5 py-1 text-xs font-medium transition-colors",
              statusFilter === value
                ? "bg-row-selected text-foreground"
                : "text-muted-foreground hover:bg-row-hover hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex-1" />
      {queryOpts ? (
        <RefreshControl
          queryKey={queryOpts.queryKey}
          dataUpdatedAt={dataUpdatedAt}
        />
      ) : null}
    </div>
  );
}
