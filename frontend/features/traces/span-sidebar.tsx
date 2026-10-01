"use client";

import type { Span, TraceDetail } from "@/lib/api/types";
import { JsonBlock } from "@/components/json-block";
import { StatusBadge } from "@/components/status-badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { formatDurationMs } from "@/lib/format";
import {
  isRedactedValue,
  spanCost,
  spanInputOutput,
  spanTokenSummary,
} from "./span-metrics";
import { kindTextClass } from "./span-kind";
import { cn } from "@/lib/cn";

type SpanSidebarProps = {
  span: Span | null;
  trace: TraceDetail;
};

function spanDurationMs(span: Span): number | null {
  if (!span.end_time) return null;
  return (
    new Date(span.end_time).getTime() - new Date(span.start_time).getTime()
  );
}

export function SpanSidebar({ span, trace }: SpanSidebarProps) {
  if (!span) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
        Select a span to inspect attributes, I/O, and events.
      </div>
    );
  }

  const tokens = spanTokenSummary(span);
  const cost = spanCost(span);
  const { input, output } = spanInputOutput(span);
  const isRoot = span.parent_span_id == null;
  const traceInput = isRoot && input === undefined ? trace.input : input;
  const traceOutput = isRoot && output === undefined ? trace.output : output;
  const duration = spanDurationMs(span);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-foreground">{span.name}</h2>
          <StatusBadge status={span.status} />
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {span.span_id}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <div>
            <dt className="text-muted-foreground">Duration</dt>
            <dd className="font-mono tabular-nums">
              {duration == null ? "—" : formatDurationMs(duration)}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Kind</dt>
            <dd className={cn("uppercase", kindTextClass(span.kind))}>
              {span.kind}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Tokens (total)</dt>
            <dd className="font-mono tabular-nums">{tokens.total}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Cost</dt>
            <dd className="font-mono tabular-nums">{cost}</dd>
          </div>
        </dl>
      </div>

      <Tabs defaultValue="attributes" className="flex min-h-0 flex-1 flex-col px-2 pb-2">
        <TabsList variant="line" className="w-full shrink-0 justify-start px-2">
          <TabsTrigger value="attributes">Attributes</TabsTrigger>
          <TabsTrigger value="io">Input / Output</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="evals">Evals</TabsTrigger>
        </TabsList>

        <TabsContent value="attributes" className="min-h-0 flex-1 data-[state=active]:flex">
          <ScrollArea className="h-full w-full flex-1">
            <AttributesTable attributes={span.attributes} />
          </ScrollArea>
        </TabsContent>

        <TabsContent value="io" className="min-h-0 flex-1 overflow-auto data-[state=active]:flex data-[state=active]:flex-col data-[state=active]:gap-3 data-[state=active]:p-2">
          <JsonBlock label="Input" value={traceInput ?? null} />
          <JsonBlock label="Output" value={traceOutput ?? null} />
        </TabsContent>

        <TabsContent value="events" className="min-h-0 flex-1 overflow-auto p-2 data-[state=active]:block">
          {span.events.length === 0 ? (
            <p className="text-sm text-muted-foreground">No events on this span.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {span.events.map((ev, i) => (
                <li key={i}>
                  <JsonBlock label={`Event ${i + 1}`} value={ev} />
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="evals" className="p-4 data-[state=active]:block">
          <p className="text-sm text-muted-foreground">
            No evaluation results for this span.
          </p>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AttributesTable({
  attributes,
}: {
  attributes: Record<string, unknown>;
}) {
  const entries = Object.entries(attributes).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  if (entries.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">No attributes.</p>
    );
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-border text-left text-muted-foreground">
          <th className="px-3 py-2 font-medium">Key</th>
          <th className="px-3 py-2 font-medium">Value</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key} className="border-b border-border/60 align-top">
            <td className="max-w-[140px] break-all px-3 py-2 font-mono text-muted-foreground">
              {key}
            </td>
            <td className="px-3 py-2">
              <AttributeValue value={value} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AttributeValue({ value }: { value: unknown }) {
  const redacted = isRedactedValue(value);
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (typeof value === "object") {
    return (
      <div className="flex flex-col gap-1">
        {redacted ? (
          <span className="text-xs text-chart-3">Redacted</span>
        ) : null}
        <pre className="max-w-full overflow-x-auto whitespace-pre-wrap font-mono text-foreground">
          {JSON.stringify(value, null, 2)}
        </pre>
      </div>
    );
  }
  return (
    <span className="font-mono break-all">
      {redacted ? (
        <>
          <span className="mr-1 text-xs text-chart-3">Redacted</span>
          {String(value)}
        </>
      ) : (
        String(value)
      )}
    </span>
  );
}
