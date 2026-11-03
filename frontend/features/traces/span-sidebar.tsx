"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ChevronRight, Search } from "lucide-react";
import type { Span, TraceDetail } from "@/lib/api/types";
import { CopyTechnicalId } from "@/components/copy-technical-id";
import { StatusBadge } from "@/components/status-badge";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";
import { formatDurationMs, formatScore } from "@/lib/format";
import { KeyValueRow, MessageList, Section, ValueView } from "./span-blocks";
import { kindTextClass } from "./span-kind";
import { buildSpanView, groupAttributes, type SpanView } from "./span-view";

type SpanSidebarProps = {
  span: Span | null;
  trace: TraceDetail;
};

const KIND_LABEL: Record<string, string> = {
  LLM: "LLM call",
  CHAIN: "Step",
  RETRIEVER: "Retrieval",
  RERANKER: "Rerank",
  TOOL: "Tool call",
  EMBEDDING: "Embedding",
  AGENT: "Agent",
};

export function SpanSidebar({ span, trace }: SpanSidebarProps) {
  const [tab, setTab] = useState("overview");

  const view = useMemo(() => (span ? buildSpanView(span) : null), [span]);

  if (!span || !view) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
        Select a step on the left to see what it received and returned.
      </div>
    );
  }

  const isRoot = span.parent_span_id == null;
  const attrCount = Object.keys(span.attributes ?? {}).length;
  const hasEvents = view.events.length > 0;
  const activeTab = tab === "events" && !hasEvents ? "overview" : tab;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              "shrink-0 text-[11px] font-semibold tracking-wide uppercase",
              kindTextClass(span.kind),
            )}
          >
            {KIND_LABEL[view.kind] ?? view.kind}
          </span>
          <h2 className="min-w-0 truncate text-sm font-semibold text-foreground" title={span.name}>
            {span.name}
          </h2>
          {span.status.toLowerCase() !== "ok" && span.status.toLowerCase() !== "unset" ? (
            <StatusBadge status={span.status} />
          ) : null}
          <span className="ml-auto shrink-0">
            <CopyTechnicalId id={span.span_id} label="Copy span ID" />
          </span>
        </div>
        <SpanFacts view={view} />
      </header>

      {view.error ? <ErrorCallout error={view.error} /> : null}

      <Tabs
        value={activeTab}
        onValueChange={(v) => setTab(v ?? "overview")}
        className="flex min-h-0 flex-1 flex-col gap-0"
      >
        <TabsList variant="line" className="w-full shrink-0 justify-start border-b border-border px-3">
          <TabsTrigger value="overview" className="flex-none px-2">Overview</TabsTrigger>
          <TabsTrigger value="attributes" className="flex-none px-2">
            Attributes <Count n={attrCount} />
          </TabsTrigger>
          {hasEvents ? (
            <TabsTrigger value="events" className="flex-none px-2">
              Events <Count n={view.events.length} />
            </TabsTrigger>
          ) : null}
        </TabsList>

        <TabsContent value="overview" className="min-h-0 flex-1 overflow-auto">
          <div className="flex flex-col gap-5 p-4">
            <SpanOverview view={view} trace={trace} isRoot={isRoot} />
          </div>
        </TabsContent>

        <TabsContent value="attributes" className="min-h-0 flex-1 overflow-auto">
          <AttributesPanel attributes={span.attributes ?? {}} />
        </TabsContent>

        {hasEvents ? (
          <TabsContent value="events" className="min-h-0 flex-1 overflow-auto">
            <EventsPanel view={view} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}

function Count({ n }: { n: number }) {
  return <span className="ml-1 text-xs tabular-nums text-muted-foreground">{n}</span>;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground tabular-nums">{children}</span>
    </span>
  );
}

/** One line of the numbers that matter; nothing rendered for what wasn't recorded. */
function SpanFacts({ view }: { view: SpanView }) {
  const { usage } = view;
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {view.durationMs != null ? (
        <Fact label="Duration">{formatDurationMs(view.durationMs)}</Fact>
      ) : null}
      {view.model ? (
        <Fact label="Model">
          {view.model}
          {view.provider ? (
            <span className="font-normal text-muted-foreground"> · {view.provider}</span>
          ) : null}
        </Fact>
      ) : null}
      {usage.total != null ? (
        <Fact label="Tokens">
          {usage.total.toLocaleString()}
          {usage.prompt != null && usage.completion != null ? (
            <span className="font-normal text-muted-foreground">
              {" "}
              ({usage.prompt.toLocaleString()} in · {usage.completion.toLocaleString()} out)
            </span>
          ) : null}
        </Fact>
      ) : null}
      {usage.cost != null ? <Fact label="Cost">${usage.cost.toFixed(4)}</Fact> : null}
    </div>
  );
}

function ErrorCallout({ error }: { error: NonNullable<SpanView["error"]> }) {
  return (
    <div className="shrink-0 border-b border-status-fail/30 bg-status-fail-bg px-4 py-2.5 text-sm text-status-fail">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {error.type ?? "This step failed"}
            {error.message ? <span className="font-normal">: {error.message}</span> : null}
          </p>
          {error.stacktrace ? (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs">Stack trace</summary>
              <pre className="mt-1 max-h-60 overflow-auto font-mono text-xs whitespace-pre-wrap">
                {error.stacktrace}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SpanOverview({
  view,
  trace,
  isRoot,
}: {
  view: SpanView;
  trace: TraceDetail;
  isRoot: boolean;
}) {
  const input = isRoot && view.input == null ? trace.input : view.input;
  const output = isRoot && view.output == null ? trace.output : view.output;

  if (view.kind === "LLM") {
    return (
      <>
        <Section
          title="Prompt"
          hint={
            view.inputMessages.length
              ? `${view.inputMessages.length} message${view.inputMessages.length === 1 ? "" : "s"} sent to the model`
              : undefined
          }
        >
          {view.inputMessages.length ? (
            <MessageList messages={view.inputMessages} />
          ) : (
            <ValueView value={input} />
          )}
        </Section>
        <Section title="Response">
          {view.outputMessages.length ? (
            <MessageList messages={view.outputMessages} emphasis />
          ) : (
            <ValueView value={output} />
          )}
        </Section>
        {view.parameters.length ? (
          <Section title="Parameters">
            <div className="flex flex-wrap gap-1.5">
              {view.parameters.map(([k, v]) => (
                <span
                  key={k}
                  className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-xs"
                >
                  <span className="text-muted-foreground">{k}</span> {v}
                </span>
              ))}
            </div>
          </Section>
        ) : null}
      </>
    );
  }

  if (view.documents) {
    return (
      <>
        <Section title="Query">
          <ValueView value={input} />
        </Section>
        <Section
          title="Documents"
          hint={`${view.documents.length} returned`}
        >
          {view.documents.length === 0 ? (
            <p className="text-sm text-status-warn">No documents were returned.</p>
          ) : (
            <ol className="flex flex-col gap-1.5">
              {view.documents.map((doc, i) => (
                <li key={`${doc.id}-${i}`} className="rounded-md border border-border bg-surface px-3 py-2">
                  <div className="flex items-baseline gap-2 text-sm">
                    <span className="text-xs tabular-nums text-muted-foreground">#{i + 1}</span>
                    <span className="min-w-0 truncate font-medium">{doc.title ?? doc.id}</span>
                    {doc.score != null ? (
                      <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">
                        score {formatScore(doc.score)}
                      </span>
                    ) : null}
                  </div>
                  {doc.text ? (
                    <p className="mt-1 line-clamp-3 text-xs whitespace-pre-wrap text-muted-foreground">
                      {doc.text}
                    </p>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </Section>
      </>
    );
  }

  return (
    <>
      <Section title="Input">
        <ValueView value={input} />
      </Section>
      <Section title="Output">
        <ValueView value={output} />
      </Section>
    </>
  );
}

function AttributesPanel({ attributes }: { attributes: Record<string, unknown> }) {
  const [filter, setFilter] = useState("");
  const groups = useMemo(() => groupAttributes(attributes), [attributes]);
  const q = filter.trim().toLowerCase();
  const shown = q
    ? groups
        .map((g) => ({
          ...g,
          collapsed: false,
          entries: g.entries.filter(
            ([k, v]) => k.toLowerCase().includes(q) || String(v).toLowerCase().includes(q),
          ),
        }))
        .filter((g) => g.entries.length > 0)
    : groups;

  if (groups.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No attributes.</p>;
  }

  return (
    <div className="flex flex-col">
      <div className="sticky top-0 z-10 border-b border-border bg-background px-3 py-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter attributes…"
            aria-label="Filter attributes"
            className="h-8 pl-8"
          />
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">No attribute matches.</p>
      ) : (
        shown.map((g) => (
          // Keyed on the filter so a search re-opens every group.
          <details key={`${g.id}-${q ? "q" : ""}`} open={!g.collapsed} className="group/g border-b border-border">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-foreground hover:bg-row-hover [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3.5 text-muted-foreground transition-transform group-open/g:rotate-90" />
              {g.label}
              <Count n={g.entries.length} />
            </summary>
            <div className="divide-y divide-border/50 pb-1">
              {g.entries.map(([k, v]) => (
                <KeyValueRow key={k} name={k} value={v} />
              ))}
            </div>
          </details>
        ))
      )}
    </div>
  );
}

function EventsPanel({ view }: { view: SpanView }) {
  return (
    <ol className="flex flex-col gap-2 p-3">
      {view.events.map((ev, i) => {
        const entries = Object.entries(ev.attributes);
        return (
          <li
            key={i}
            className={cn(
              "rounded-md border border-border bg-surface",
              ev.name === "exception" && "border-status-fail/40",
            )}
          >
            <div className="flex items-baseline gap-2 px-3 py-2 text-sm">
              <span
                className={cn("font-medium", ev.name === "exception" && "text-status-fail")}
              >
                {ev.name}
              </span>
              {ev.offsetMs != null ? (
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                  +{formatDurationMs(ev.offsetMs)}
                </span>
              ) : null}
            </div>
            {entries.length ? (
              <div className="divide-y divide-border/50 border-t border-border/60">
                {entries.map(([k, v]) => (
                  <KeyValueRow key={k} name={k} value={v} />
                ))}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
