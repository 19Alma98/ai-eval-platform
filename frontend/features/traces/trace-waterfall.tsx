"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type UIEvent,
} from "react";
import { ChevronDown, ChevronRight, ChevronUp, Search } from "lucide-react";
import type { Span, TraceDetail } from "@/lib/api/types";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { formatDurationMs } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  buildSpanTree,
  flattenVisible,
  type FlatSpanRow,
} from "./build-span-tree";

const ROW_HEIGHT = 32;
const VIRTUALIZE_THRESHOLD = 200;
const OVERSCAN = 8;

type TraceWaterfallProps = {
  trace: TraceDetail;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
};

function traceBounds(trace: TraceDetail): { start: number; end: number } {
  const start = new Date(trace.start_time).getTime();
  let end = trace.end_time
    ? new Date(trace.end_time).getTime()
    : start;
  for (const span of trace.spans) {
    if (span.end_time) {
      end = Math.max(end, new Date(span.end_time).getTime());
    }
  }
  if (end <= start) end = start + 1;
  return { start, end };
}

function spanDurationMs(span: Span): number {
  if (!span.end_time) return 0;
  return (
    new Date(span.end_time).getTime() - new Date(span.start_time).getTime()
  );
}

function kindBarClass(kind: string): string {
  const k = kind.toUpperCase();
  if (k === "LLM") return "bg-kind-llm/35 border-kind-llm/50";
  if (k === "CHAIN") return "bg-kind-chain/35 border-kind-chain/50";
  if (k === "RETRIEVER") return "bg-kind-retriever/35 border-kind-retriever/50";
  if (k === "TOOL") return "bg-kind-tool/35 border-kind-tool/50";
  return "bg-kind-other/35 border-kind-other/50";
}

function kindTextClass(kind: string): string {
  const k = kind.toUpperCase();
  if (k === "LLM") return "text-kind-llm";
  if (k === "CHAIN") return "text-kind-chain";
  if (k === "RETRIEVER") return "text-kind-retriever";
  if (k === "TOOL") return "text-kind-tool";
  return "text-kind-other";
}

function spanMatchesSearch(span: Span, query: string): boolean {
  if (!query) return false;
  const q = query.toLowerCase();
  if (span.name.toLowerCase().includes(q)) return true;
  if (span.kind.toLowerCase().includes(q)) return true;
  try {
    const attrs = JSON.stringify(span.attributes).toLowerCase();
    if (attrs.includes(q)) return true;
  } catch {
    /* ignore */
  }
  return false;
}

export function TraceWaterfall({
  trace,
  selectedSpanId,
  onSelectSpan,
}: TraceWaterfallProps) {
  const tree = useMemo(() => buildSpanTree(trace.spans), [trace.spans]);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [search, setSearch] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);

  const rows = useMemo(
    () => flattenVisible(tree, collapsed),
    [tree, collapsed],
  );

  const matchIds = useMemo(() => {
    if (!search.trim()) return [];
    return rows
      .filter((r) => spanMatchesSearch(r.node.span, search.trim()))
      .map((r) => r.node.span.span_id);
  }, [rows, search]);

  useEffect(() => {
    setMatchIndex(0);
  }, [search, matchIds.length]);

  const activeMatchId = matchIds[matchIndex] ?? null;

  const bounds = useMemo(() => traceBounds(trace), [trace]);
  const durationMs = bounds.end - bounds.start;

  const toggleCollapsed = useCallback((spanId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(spanId)) next.delete(spanId);
      else next.add(spanId);
      return next;
    });
  }, []);

  const virtualize = trace.spans.length > VIRTUALIZE_THRESHOLD;
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(400);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setViewportHeight(el.clientHeight);
    });
    ro.observe(el);
    setViewportHeight(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  const onScroll = useCallback((e: UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  const { sliceStart, sliceEnd, paddingTop, paddingBottom } = useMemo(() => {
    if (!virtualize) {
      return {
        sliceStart: 0,
        sliceEnd: rows.length,
        paddingTop: 0,
        paddingBottom: 0,
      };
    }
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
    const visible = Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN * 2;
    const end = Math.min(rows.length, start + visible);
    return {
      sliceStart: start,
      sliceEnd: end,
      paddingTop: start * ROW_HEIGHT,
      paddingBottom: Math.max(0, (rows.length - end) * ROW_HEIGHT),
    };
  }, [virtualize, scrollTop, viewportHeight, rows.length]);

  const visibleRows = virtualize
    ? rows.slice(sliceStart, sliceEnd)
    : rows;

  const midLabel = formatDurationMs(durationMs / 2);
  const endLabel = formatDurationMs(durationMs);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search spans…"
            className="h-8 pl-8"
            aria-label="Search spans"
          />
        </div>
        {matchIds.length > 0 ? (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <span>
              {matchIndex + 1}/{matchIds.length}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Previous match"
              onClick={() =>
                setMatchIndex((i) =>
                  matchIds.length ? (i - 1 + matchIds.length) % matchIds.length : 0,
                )
              }
            >
              <ChevronUp className="size-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Next match"
              onClick={() =>
                setMatchIndex((i) =>
                  matchIds.length ? (i + 1) % matchIds.length : 0,
                )
              }
            >
              <ChevronDown className="size-3.5" />
            </Button>
          </div>
        ) : search.trim() ? (
          <span className="text-xs text-muted-foreground">No matches</span>
        ) : null}
      </div>

      <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_minmax(120px,28%)] gap-2 border-b border-border bg-surface px-3 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>Span</span>
        <div className="relative flex justify-between font-mono tabular-nums normal-case">
          <span>0</span>
          <span>{midLabel}</span>
          <span>{endLabel}</span>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto"
        onScroll={onScroll}
      >
        <div style={{ paddingTop, paddingBottom }}>
          {visibleRows.map((row, i) => (
            <WaterfallRow
              key={row.node.span.span_id}
              row={row}
              bounds={bounds}
              durationMs={durationMs}
              selected={selectedSpanId === row.node.span.span_id}
              highlighted={activeMatchId === row.node.span.span_id}
              search={search.trim()}
              collapsed={collapsed.has(row.node.span.span_id)}
              onToggleCollapse={() => toggleCollapsed(row.node.span.span_id)}
              onSelect={() => onSelectSpan(row.node.span.span_id)}
              index={virtualize ? sliceStart + i : i}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function WaterfallRow({
  row,
  bounds,
  durationMs,
  selected,
  highlighted,
  search,
  collapsed,
  onToggleCollapse,
  onSelect,
}: {
  row: FlatSpanRow;
  bounds: { start: number; end: number };
  durationMs: number;
  selected: boolean;
  highlighted: boolean;
  search: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: () => void;
  index: number;
}) {
  const span = row.node.span;
  const spanStart = new Date(span.start_time).getTime();
  const spanEnd = span.end_time
    ? new Date(span.end_time).getTime()
    : spanStart;
  const leftPct = ((spanStart - bounds.start) / durationMs) * 100;
  const widthPct = Math.max(
    0.5,
    ((spanEnd - spanStart) / durationMs) * 100,
  );
  const dur = spanDurationMs(span);
  const isMatch = search ? spanMatchesSearch(span, search) : false;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "grid h-8 cursor-pointer grid-cols-[minmax(0,1fr)_minmax(120px,28%)] items-center gap-2 border-b border-border/50 px-2 text-xs transition-colors",
        selected && "bg-row-selected",
        !selected && "hover:bg-row-hover",
        highlighted && "ring-1 ring-inset ring-chart-1",
        isMatch && !selected && "bg-chart-1/10",
      )}
      style={{ minHeight: ROW_HEIGHT }}
    >
      <div
        className="flex min-w-0 items-center gap-1"
        style={{ paddingLeft: row.depth * 12 }}
      >
        {row.hasChildren ? (
          <button
            type="button"
            className="flex size-5 shrink-0 items-center justify-center rounded hover:bg-muted"
            aria-label={collapsed ? "Expand" : "Collapse"}
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse();
            }}
          >
            {collapsed ? (
              <ChevronRight className="size-3.5" />
            ) : (
              <ChevronDown className="size-3.5" />
            )}
          </button>
        ) : (
          <span className="inline-block size-5 shrink-0" />
        )}
        <span className="truncate font-medium">{span.name}</span>
        <span className={cn("shrink-0 text-[10px] uppercase", kindTextClass(span.kind))}>
          {span.kind}
        </span>
        <StatusBadge status={span.status} className="ml-auto shrink-0 scale-90" />
      </div>
      <div className="relative h-4 rounded-sm bg-muted/40">
        <div
          className={cn(
            "absolute top-0 h-full min-w-[2px] rounded-sm border",
            kindBarClass(span.kind),
          )}
          style={{
            left: `${Math.min(100, Math.max(0, leftPct))}%`,
            width: `${Math.min(100 - leftPct, widthPct)}%`,
          }}
          title={formatDurationMs(dur)}
        />
      </div>
    </div>
  );
}
