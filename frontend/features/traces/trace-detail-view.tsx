"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { CopyTechnicalId } from "@/components/copy-technical-id";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import type { Layout } from "react-resizable-panels";
import { ApiError } from "@/lib/api/client";
import { getTrace } from "@/lib/api/traces";
import { formatDurationMs } from "@/lib/format";
import { SpanSidebar } from "./span-sidebar";
import { TraceWaterfall } from "./trace-waterfall";

const SPLIT_STORAGE_KEY = "aiobs.traceDetail.split";
const PANEL_WATERFALL = "waterfall";
const PANEL_SIDEBAR = "sidebar";

const DEFAULT_SPLIT: Layout = {
  [PANEL_WATERFALL]: 62,
  [PANEL_SIDEBAR]: 38,
};

function readSplit(): Layout {
  if (typeof window === "undefined") return DEFAULT_SPLIT;
  try {
    const raw = sessionStorage.getItem(SPLIT_STORAGE_KEY);
    if (!raw) return DEFAULT_SPLIT;
    const parsed = JSON.parse(raw) as Layout;
    if (
      typeof parsed[PANEL_WATERFALL] === "number" &&
      typeof parsed[PANEL_SIDEBAR] === "number"
    ) {
      return parsed;
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_SPLIT;
}

type TraceDetailViewProps = {
  projectId: string;
  traceId: string;
};

export function TraceDetailView({ projectId, traceId }: TraceDetailViewProps) {
  const query = useQuery({
    queryKey: ["trace", projectId, traceId],
    queryFn: () => getTrace(projectId, traceId),
  });

  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [defaultLayout, setDefaultLayout] = useState<Layout | null>(null);

  useEffect(() => {
    setDefaultLayout(readSplit());
  }, []);

  const trace = query.data;

  const selectedSpan = useMemo(() => {
    if (!trace || !selectedSpanId) return null;
    return trace.spans.find((s) => s.span_id === selectedSpanId) ?? null;
  }, [trace, selectedSpanId]);

  useEffect(() => {
    if (trace && trace.spans.length > 0 && !selectedSpanId) {
      const root =
        trace.spans.find((s) => s.parent_span_id == null) ?? trace.spans[0];
      setSelectedSpanId(root.span_id);
    }
  }, [trace, selectedSpanId]);

  const onLayoutChanged = useCallback((layout: Layout) => {
    sessionStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(layout));
  }, []);

  const durationMs = useMemo(() => {
    if (!trace?.end_time) return null;
    return (
      new Date(trace.end_time).getTime() -
      new Date(trace.start_time).getTime()
    );
  }, [trace]);

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[320px]" />;
  }

  if (query.isError || !trace) {
    const err = query.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Could not load trace"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const backHref = `/traces?project=${encodeURIComponent(projectId)}`;

  return (
    <div className="flex h-[calc(100vh-var(--app-header-height,3.5rem)-2rem)] min-h-[480px] flex-col gap-3">
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
            <h1 className="text-lg font-semibold text-foreground">{trace.name}</h1>
            <StatusBadge status={trace.status} />
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>
              Duration{" "}
              <span className="font-mono tabular-nums text-foreground">
                {durationMs == null ? "—" : formatDurationMs(durationMs)}
              </span>
            </span>
            <span>
              Spans{" "}
              <span className="font-mono tabular-nums text-foreground">
                {trace.spans.length}
              </span>
            </span>
            <span>
              Start{" "}
              <RelativeTime date={trace.start_time} />
            </span>
            <CopyTechnicalId id={trace.trace_id} label="Copy trace ID" />
          </div>
        </div>
      </div>

      {defaultLayout ? (
        <ResizablePanelGroup
          orientation="horizontal"
          className="min-h-0 flex-1 rounded-lg border border-border"
          onLayoutChanged={onLayoutChanged}
          defaultLayout={defaultLayout}
        >
          <ResizablePanel id={PANEL_WATERFALL} minSize={35}>
            <TraceWaterfall
              trace={trace}
              selectedSpanId={selectedSpanId}
              onSelectSpan={setSelectedSpanId}
            />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel id={PANEL_SIDEBAR} minSize={25}>
            <SpanSidebar span={selectedSpan} trace={trace} />
          </ResizablePanel>
        </ResizablePanelGroup>
      ) : (
        <LoadingBlock className="min-h-[240px] flex-1" />
      )}
    </div>
  );
}
