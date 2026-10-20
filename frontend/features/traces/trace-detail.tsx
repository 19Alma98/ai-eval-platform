"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Link2 } from "lucide-react";
import { toast } from "sonner";
import { CopyTechnicalId } from "@/components/copy-technical-id";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetaItem, PageHeader } from "@/components/page-header";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, formatErrorForUi, withBasePath } from "@/lib/api/client";
import { formatDurationMs, formatScore, truncateId } from "@/lib/format";
import { liveRunHref, traceHref } from "@/lib/links";
import { withProjectQuery } from "@/lib/project-href";
import { RagPipeline } from "./rag-pipeline";
import { liveTraceSkipped } from "./live-skip";
import { buildRagView, hasRagContent } from "./rag-view";
import { SpanSidebar } from "./span-sidebar";
import { traceUsage } from "./span-metrics";
import { TraceWaterfall } from "./trace-waterfall";
import { useTrace, useTraceLiveInteraction } from "./use-traces";

async function copyLink(href: string) {
  try {
    await navigator.clipboard.writeText(new URL(withBasePath(href), window.location.origin).toString());
    toast.success("Link copied");
  } catch {
    toast.error("Could not copy");
  }
}

export function TraceDetailView({ projectId, traceId }: { projectId: string; traceId: string }) {
  const query = useTrace(projectId, traceId);
  const trace = query.data;
  const live = useTraceLiveInteraction(trace?.live_interaction_id);
  const [tab, setTab] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);

  const ragView = useMemo(() => (trace ? buildRagView(trace) : null), [trace]);
  const usage = useMemo(() => traceUsage(trace?.spans ?? []), [trace]);

  if (query.isLoading) return <LoadingBlock className="min-h-[240px]" />;
  if (query.isError || !trace || !ragView) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <ErrorState
        title={notFound ? "Trace not found" : "Could not load trace"}
        message={
          notFound
            ? "It may belong to another project, or it has not been exported yet."
            : formatErrorForUi(query.error)
        }
        onRetry={notFound ? undefined : () => void query.refetch()}
      />
    );
  }

  const rootSpanId =
    (trace.spans.find((s) => s.parent_span_id == null) ?? trace.spans[0])?.span_id ?? null;
  const effectiveSpanId = selectedSpanId ?? rootSpanId;
  const selectedSpan = trace.spans.find((s) => s.span_id === effectiveSpanId) ?? null;
  const showRag = hasRagContent(ragView);
  const activeTab = tab ?? (showRag ? "rag" : "timeline");
  const durationMs = trace.end_time
    ? new Date(trace.end_time).getTime() - new Date(trace.start_time).getTime()
    : null;

  function openSpan(spanId: string) {
    setSelectedSpanId(spanId);
    setTab("timeline");
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumbs={[
          { label: "Traces", href: withProjectQuery("/traces", projectId) },
          { label: truncateId(trace.trace_id, 12) },
        ]}
        title={trace.name || "Trace"}
        badges={<StatusBadge status={trace.status} />}
        meta={
          <>
            <MetaItem label="Started">
              <RelativeTime date={trace.start_time} />
            </MetaItem>
            {durationMs != null ? (
              <MetaItem label="Duration">{formatDurationMs(durationMs)}</MetaItem>
            ) : null}
            <MetaItem label="Steps">{trace.spans.length}</MetaItem>
            {usage.tokens != null ? (
              <MetaItem label="Tokens">{Math.round(usage.tokens).toLocaleString()}</MetaItem>
            ) : null}
            {usage.cost != null ? (
              <MetaItem label="Cost">${usage.cost.toFixed(4)}</MetaItem>
            ) : null}
            {trace.environment ? (
              <MetaItem label="Environment">{trace.environment}</MetaItem>
            ) : null}
            {trace.session_id ? (
              <MetaItem label="Session">
                <Link
                  className="hover:text-primary hover:underline"
                  href={withProjectQuery(
                    `/traces?range=all&q=${encodeURIComponent(trace.session_id)}`,
                    projectId,
                  )}
                >
                  {truncateId(trace.session_id, 16)}
                </Link>
              </MetaItem>
            ) : null}
            {trace.user_id ? <MetaItem label="User">{trace.user_id}</MetaItem> : null}
            <span className="inline-flex items-center gap-1 font-mono text-xs">
              {truncateId(trace.trace_id, 16)}
              <CopyTechnicalId id={trace.trace_id} label="Copy trace ID" />
            </span>
          </>
        }
        actions={
          <>
            {trace.live_interaction_id ? (
              <Button
                size="sm"
                variant="outline"
                render={<Link href={liveRunHref(projectId, trace.live_interaction_id)} />}
              >
                Judge verdict &amp; review
              </Button>
            ) : null}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void copyLink(traceHref(projectId, trace.trace_id))}
            >
              <Link2 className="size-4" />
              Copy link
            </Button>
          </>
        }
        className="mb-0"
      />

      {liveTraceSkipped(trace) ? (
        <p className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn">
          This call is marked live but did not become a Live traffic answer: no question or
          answer could be read from it. Check that the server runs with{" "}
          <code>CONTENT_CAPTURE_ENABLED=true</code>; if the function takes several text arguments
          or returns no text, call <code>opengrade.set_input(question)</code> and{" "}
          <code>opengrade.set_output(answer)</code> inside it.
        </p>
      ) : null}

      {(trace.scores ?? []).length > 0 ? (
        <div className="flex flex-wrap gap-1.5" aria-label="Trace scores">
          {(trace.scores ?? []).map((s) => (
            <span
              key={s.id}
              title={s.explanation ?? undefined}
              className="inline-flex items-center gap-1.5 rounded border border-border bg-surface px-2 py-1 text-xs"
            >
              <span className="text-foreground">{s.name}</span>
              {s.value != null ? (
                <span className="font-medium tabular-nums">{formatScore(s.value)}</span>
              ) : null}
              {s.label ? <StatusBadge status={s.label} /> : null}
            </span>
          ))}
        </div>
      ) : null}

      <Tabs value={activeTab} onValueChange={(v) => setTab(v)}>
        <TabsList variant="line">
          <TabsTrigger value="rag" isDisabled={!showRag}>
            RAG view
          </TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
        </TabsList>
        <TabsContent value="rag" className="pt-2">
          <div className="mx-auto max-w-4xl">
            <RagPipeline view={ragView} interaction={live.data} onOpenSpan={openSpan} />
          </div>
        </TabsContent>
        <TabsContent value="timeline" className="pt-2">
          <ResizablePanelGroup
            orientation="horizontal"
            className="h-[min(720px,75vh)] min-h-[360px] rounded-md border border-border"
            defaultLayout={{ waterfall: 58, sidebar: 42 }}
          >
            <ResizablePanel id="waterfall" minSize={30}>
              <TraceWaterfall
                trace={trace}
                selectedSpanId={effectiveSpanId}
                onSelectSpan={setSelectedSpanId}
              />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id="sidebar" minSize={25}>
              <SpanSidebar span={selectedSpan} trace={trace} />
            </ResizablePanel>
          </ResizablePanelGroup>
        </TabsContent>
      </Tabs>
    </div>
  );
}
