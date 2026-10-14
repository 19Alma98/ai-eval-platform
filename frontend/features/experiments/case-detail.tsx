"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { CheckCircle2, ChevronDown, ChevronRight, XCircle } from "lucide-react";
import { JsonBlock } from "@/components/json-block";
import { JudgeClaimsTable } from "@/components/judge-claims-table";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";
import { experimentItemHref, traceHref } from "@/lib/links";
import {
  contextStats,
  parseRetrievedDocuments,
  type CaseMetricResult,
  type CaseView,
  type Outcome,
} from "./case-results";
import { RunItemTimeline } from "./run-item-timeline";

async function copyItemLink(href: string) {
  try {
    await navigator.clipboard.writeText(new URL(href, window.location.origin).toString());
    toast.success("Link copied");
  } catch {
    toast.error("Could not copy");
  }
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const OUTCOME_LABEL: Record<Outcome, string> = {
  pass: "pass",
  fail: "fail",
  skipped: "skipped",
  error: "error",
  scored: "scored",
  pending: "pending",
};

function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function TextBox({ children, tone }: { children: ReactNode; tone?: "muted" }) {
  return (
    <div
      className={cn(
        "max-h-[220px] overflow-auto rounded-md border border-border px-3 py-2 text-sm whitespace-pre-wrap break-words",
        tone === "muted" ? "bg-surface-2 text-foreground" : "bg-surface text-foreground",
      )}
    >
      {children}
    </div>
  );
}

function MetricResultRow({ result }: { result: CaseMetricResult }) {
  const [open, setOpen] = useState(result.outcome === "fail" || result.outcome === "error");
  const hasClaims =
    Array.isArray(result.metadata?.claims) || Array.isArray(result.metadata?.answer_claims);
  const expandable = Boolean(result.explanation?.trim()) || hasClaims;

  return (
    <li className="rounded-md border border-border bg-surface">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        disabled={!expandable}
      >
        {expandable ? (
          open ? (
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
          )
        ) : (
          <span className="size-3.5 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={result.metric.description}>
          {result.metric.label}
        </span>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatScore(result.score)}
        </span>
        <StatusBadge status={OUTCOME_LABEL[result.outcome]} className="shrink-0" />
      </button>
      {open && expandable ? (
        <div className="flex flex-col gap-2 border-t border-border px-3 py-2">
          {result.explanation?.trim() ? (
            <p className="text-sm whitespace-pre-wrap text-muted-foreground">
              {result.explanation.trim()}
            </p>
          ) : null}
          <JudgeClaimsTable metadata={result.metadata} title="Claims checked" />
          <JudgeClaimsTable
            metadata={result.metadata}
            claimsKey="answer_claims"
            title="Answer claims vs expected answer"
          />
        </div>
      ) : null}
    </li>
  );
}

function DocumentCard({
  index,
  id,
  title,
  text,
  expected,
}: {
  index: number;
  id: string | null;
  title: string | null;
  text: string;
  expected: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > 280;
  return (
    <li className="rounded-md border border-border bg-surface px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tabular-nums text-muted-foreground">#{index}</span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {title ?? id ?? "Untitled document"}
        </span>
        {id && title ? (
          <Badge variant="outline" className="font-normal">
            {id}
          </Badge>
        ) : null}
        {expected ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-status-ok">
            <CheckCircle2 className="size-3.5" />
            Expected
          </span>
        ) : null}
      </div>
      <p
        className={cn(
          "mt-1 text-sm whitespace-pre-wrap text-muted-foreground",
          !expanded && long && "line-clamp-3",
        )}
      >
        {text || "—"}
      </p>
      {long ? (
        <button
          type="button"
          className="mt-1 text-xs text-primary hover:underline"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      ) : null}
    </li>
  );
}

export function CaseDetail({
  projectId,
  experimentId,
  item,
  position,
  total,
}: {
  projectId: string;
  experimentId: string;
  item: CaseView;
  position: number;
  total: number;
}) {
  const [showTrace, setShowTrace] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const docs = parseRetrievedDocuments(item.retrievedDocuments);
  const expected = new Set(item.expectedDocIds);
  const retrievedIds = new Set((docs ?? []).map((d) => d.id).filter(Boolean) as string[]);
  const missing = item.expectedDocIds.filter((id) => !retrievedIds.has(id));
  const stats = contextStats(item.context);
  const answer = asText(item.actualOutput);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">
          Question {position} of {total}
        </span>
        {item.nScored > 0 ? (
          <span
            className={cn(
              "inline-flex items-center gap-1 text-sm font-medium",
              item.failed.length > 0 ? "text-status-fail" : "text-status-ok",
            )}
          >
            {item.failed.length > 0 ? (
              <XCircle className="size-4" />
            ) : (
              <CheckCircle2 className="size-4" />
            )}
            {item.nPassed}/{item.nScored} metrics passed
          </span>
        ) : null}
      </div>

      <Section title="Question">
        <TextBox>{asText(item.question) || "—"}</TextBox>
      </Section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="App answer">
          <TextBox>
            {answer || (
              <span className="text-muted-foreground">
                No answer received yet for this question.
              </span>
            )}
          </TextBox>
        </Section>
        <Section title="Expected answer">
          <TextBox tone="muted">{asText(item.expectedAnswer) || "—"}</TextBox>
        </Section>
      </div>

      {item.results.length > 0 ? (
        <Section title="Metric results">
          <ul className="flex flex-col gap-1.5">
            {item.results.map((result) => (
              <MetricResultRow key={result.metric.runId} result={result} />
            ))}
          </ul>
        </Section>
      ) : null}

      <Section
        title="Retrieved documents"
        aside={
          docs && docs.length > 0 ? (
            <span className="text-xs text-muted-foreground">
              {docs.length} retrieved
            </span>
          ) : null
        }
      >
        {docs === null ? (
          <p className="text-sm text-muted-foreground">
            Your app did not report retrieved documents for this answer.
          </p>
        ) : docs.length === 0 ? (
          <p className="text-sm text-status-warn">No documents were retrieved.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {docs.map((doc, i) => (
              <DocumentCard
                key={`${doc.id ?? "doc"}-${i}`}
                index={i + 1}
                id={doc.id}
                title={doc.title}
                text={doc.text}
                expected={doc.id != null && expected.has(doc.id)}
              />
            ))}
          </ul>
        )}
        {missing.length > 0 ? (
          <p className="text-xs text-status-fail">
            Expected but not retrieved: {missing.join(", ")}
          </p>
        ) : null}
      </Section>

      {stats.length > 0 ? (
        <Section title="Performance">
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {stats.map((stat) => (
              <div key={stat.label} className="flex gap-1.5">
                <dt className="text-muted-foreground">{stat.label}</dt>
                <dd className="tabular-nums text-foreground">{stat.value}</dd>
              </div>
            ))}
          </dl>
        </Section>
      ) : null}

      <div className="flex flex-wrap gap-3 border-t border-border pt-3 text-xs">
        {item.sourceTraceId ? (
          <button
            type="button"
            className="text-primary hover:underline"
            onClick={() => setShowTrace((v) => !v)}
            aria-expanded={showTrace}
          >
            {showTrace ? "Hide execution steps" : "Show execution steps"}
          </button>
        ) : null}
        {item.sourceTraceId ? (
          <Link href={traceHref(projectId, item.sourceTraceId)} className="text-primary hover:underline">
            Open trace
          </Link>
        ) : null}
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground hover:underline"
          onClick={() => void copyItemLink(experimentItemHref(projectId, experimentId, item.datasetItemId))}
        >
          Copy link to this answer
        </button>
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground hover:underline"
          onClick={() => setShowRaw((v) => !v)}
          aria-expanded={showRaw}
        >
          {showRaw ? "Hide raw data" : "Show raw data"}
        </button>
      </div>
      {showTrace && item.sourceTraceId ? (
        <RunItemTimeline projectId={projectId} traceId={item.sourceTraceId} />
      ) : null}
      {showRaw ? (
        <JsonBlock value={{ context: item.context, output: item.actualOutput }} />
      ) : null}
    </div>
  );
}
