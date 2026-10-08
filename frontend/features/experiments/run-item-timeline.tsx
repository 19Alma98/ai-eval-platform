"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoadingBlock } from "@/components/loading-block";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { formatErrorForUi } from "@/lib/api/client";
import { getTrace } from "@/lib/api/traces";
import { SpanSidebar } from "@/features/traces/span-sidebar";
import { TraceWaterfall } from "@/features/traces/trace-waterfall";

type RunItemTimelineProps = {
  projectId: string;
  traceId: string;
};

export function RunItemTimeline({ projectId, traceId }: RunItemTimelineProps) {
  const query = useQuery({
    queryKey: ["trace", projectId, traceId],
    queryFn: () => getTrace(projectId, traceId),
  });

  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const trace = query.data;

  const traceScopeKey = `${projectId}:${traceId}`;
  const [prevTraceScopeKey, setPrevTraceScopeKey] = useState(traceScopeKey);
  if (traceScopeKey !== prevTraceScopeKey) {
    setPrevTraceScopeKey(traceScopeKey);
    setSelectedSpanId(null);
  }

  const defaultSpanId = useMemo(() => {
    if (!trace || trace.spans.length === 0) return null;
    const root =
      trace.spans.find((s) => s.parent_span_id == null) ?? trace.spans[0];
    return root.span_id;
  }, [trace]);

  const effectiveSelectedSpanId = selectedSpanId ?? defaultSpanId;

  const selectedSpan = useMemo(() => {
    if (!trace || !effectiveSelectedSpanId) return null;
    return (
      trace.spans.find((s) => s.span_id === effectiveSelectedSpanId) ?? null
    );
  }, [trace, effectiveSelectedSpanId]);

  if (query.isLoading) {
    return <LoadingBlock className="h-[220px]" />;
  }

  if (query.isError || !trace) {
    const err = query.error;
    const message = formatErrorForUi(err);
    return (
      <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-muted-foreground">
        Trace timeline unavailable: {message}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-xs font-medium text-muted-foreground">
        Source trace timeline
      </h4>
      <ResizablePanelGroup
        orientation="horizontal"
        className="h-[min(280px,40vh)] min-h-[200px] rounded-md border border-border"
        defaultLayout={{ waterfall: 58, sidebar: 42 }}
      >
        <ResizablePanel id="waterfall" minSize={30}>
          <TraceWaterfall
            trace={trace}
            selectedSpanId={effectiveSelectedSpanId}
            onSelectSpan={setSelectedSpanId}
          />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id="sidebar" minSize={25}>
          <SpanSidebar span={selectedSpan} trace={trace} />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
