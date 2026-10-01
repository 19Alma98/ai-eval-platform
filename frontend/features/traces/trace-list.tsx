"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import type { TraceSummary } from "@/lib/api/types";
import { formatDurationMs, truncateId } from "@/lib/format";
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

async function copyTraceId(id: string, e: React.MouseEvent) {
  e.stopPropagation();
  try {
    await navigator.clipboard.writeText(id);
    toast.success("Trace ID copied");
  } catch {
    toast.error("Could not copy");
  }
}

export function TraceList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const { start, end } = useTimeRange();
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

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
      {
        id: "trace_id",
        header: "Trace ID",
        headerClassName: "w-[140px]",
        cell: (row) => (
          <div className="flex items-center gap-1">
            <span className="font-mono text-xs text-muted-foreground">
              {truncateId(row.trace_id, 10)}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="size-6 shrink-0"
              aria-label={`Copy trace ID ${row.trace_id}`}
              onClick={(e) => copyTraceId(row.trace_id, e)}
            >
              <Copy className="size-3" />
            </Button>
          </div>
        ),
      },
    ],
    [],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
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
          onStatusFilterChange={setStatusFilter}
          queryOpts={queryOpts}
          dataUpdatedAt={query.dataUpdatedAt}
        />
        <EmptyState
          title="Traces"
          description="No traces yet. Run the OTLP example against this project."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <TraceListToolbar
        statusFilter={statusFilter}
        onStatusFilterChange={(v) => {
          setStatusFilter(v);
          setSelectedIndex(0);
        }}
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
