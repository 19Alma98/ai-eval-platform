"use client";

import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { JsonBlock } from "@/components/json-block";
import { cn } from "@/lib/cn";
import type { SpanMessage } from "./span-view";
import { isRedactedValue } from "./span-metrics";

/** Building blocks shared by the span panel and the RAG view. */

const ROLE_STYLE: Record<string, string> = {
  system: "bg-surface-2 text-muted-foreground",
  user: "bg-kind-chain/15 text-kind-chain",
  human: "bg-kind-chain/15 text-kind-chain",
  assistant: "bg-kind-llm/15 text-kind-llm",
  ai: "bg-kind-llm/15 text-kind-llm",
  model: "bg-kind-llm/15 text-kind-llm",
  tool: "bg-kind-tool/15 text-kind-tool",
  function: "bg-kind-tool/15 text-kind-tool",
};

export function Section({
  title,
  hint,
  children,
  className,
}: {
  title: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-baseline gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {title}
        </h3>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** Long text, clamped with a toggle so one big system prompt doesn't bury the rest. */
export function ClampedText({
  text,
  lines = 8,
  mono = false,
  className,
}: {
  text: string;
  lines?: number;
  mono?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const long = text.length > 600 || text.split("\n").length > lines;
  return (
    <div className={className}>
      <p
        className={cn(
          "break-words whitespace-pre-wrap",
          mono ? "font-mono text-xs leading-relaxed" : "text-sm leading-relaxed",
          long && !open && "line-clamp-[var(--clamp)]",
        )}
        style={{ "--clamp": lines } as React.CSSProperties}
      >
        {text}
      </p>
      {long ? (
        <button
          type="button"
          className="mt-1 text-xs text-primary hover:underline"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Show less" : `Show all (${text.length.toLocaleString()} chars)`}
        </button>
      ) : null}
    </div>
  );
}

function ToolCallBlock({ name, args }: { name: string; args: string | null }) {
  return (
    <div className="rounded border border-border bg-surface-2/60 px-2 py-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-kind-tool">
        <Wrench className="size-3" aria-hidden />
        <span className="font-mono">{name}</span>
      </div>
      {args ? (
        <pre className="mt-1 max-h-48 overflow-auto font-mono text-xs whitespace-pre-wrap text-foreground">
          {prettyJson(args)}
        </pre>
      ) : null}
    </div>
  );
}

function prettyJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

/** A chat transcript: one card per message, role on top. */
export function MessageList({
  messages,
  emphasis = false,
}: {
  messages: SpanMessage[];
  emphasis?: boolean;
}) {
  return (
    <ol className="flex flex-col gap-2">
      {messages.map((m, i) => {
        const role = m.role.toLowerCase();
        return (
          <li
            key={i}
            className={cn(
              "rounded-md border border-border bg-surface px-3 py-2",
              emphasis && "border-kind-llm/40",
            )}
          >
            <span
              className={cn(
                "mb-1.5 inline-block rounded px-1.5 py-0.5 text-[11px] font-medium capitalize",
                ROLE_STYLE[role] ?? "bg-surface-2 text-muted-foreground",
              )}
            >
              {m.role}
            </span>
            {m.content ? (
              <ClampedText text={m.content} lines={role === "system" ? 4 : 12} />
            ) : null}
            {m.toolCalls.length > 0 ? (
              <div className={cn("flex flex-col gap-1.5", m.content && "mt-2")}>
                {m.toolCalls.map((c, j) => (
                  <ToolCallBlock key={j} name={c.name} args={c.arguments} />
                ))}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function isScalar(v: unknown): v is string | number | boolean | null {
  return v === null || ["string", "number", "boolean"].includes(typeof v);
}

/** A captured input/output value, rendered by shape rather than as raw JSON. */
export function ValueView({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <p className="text-sm text-muted-foreground">Not captured</p>;
  }
  if (typeof value === "string") {
    return (
      <div className="rounded-md border border-border bg-surface px-3 py-2">
        <ClampedText text={value} lines={12} />
      </div>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <p className="rounded-md border border-border bg-surface px-3 py-2 font-mono text-sm">
        {String(value)}
      </p>
    );
  }
  if (
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length <= 16 &&
    Object.values(value).every(isScalar)
  ) {
    return (
      <div className="divide-y divide-border/60 rounded-md border border-border bg-surface">
        {Object.entries(value).map(([k, v]) => (
          <KeyValueRow key={k} name={k} value={v} />
        ))}
      </div>
    );
  }
  return <JsonBlock value={value} />;
}

function decodeIfJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const t = value.trim();
  if (!(t.startsWith("{") || t.startsWith("["))) return value;
  try {
    return JSON.parse(t);
  } catch {
    return value;
  }
}

/**
 * One attribute. Short scalars sit next to their key; anything long or
 * structured drops below it at full width and starts folded.
 */
export function KeyValueRow({ name, value }: { name: string; value: unknown }) {
  const decoded = decodeIfJson(value);
  const redacted = isRedactedValue(value);
  const inline =
    decoded === null ||
    decoded === undefined ||
    typeof decoded === "number" ||
    typeof decoded === "boolean" ||
    (typeof decoded === "string" && decoded.length <= 80 && !decoded.includes("\n"));

  if (inline) {
    return (
      <div className="flex items-baseline gap-3 px-3 py-1.5 text-xs">
        <span className="w-2/5 shrink-0 font-mono break-all text-muted-foreground">{name}</span>
        <span className="min-w-0 flex-1 font-mono break-all text-foreground">
          {redacted ? <RedactedTag /> : null}
          {decoded === null || decoded === undefined ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            String(decoded)
          )}
        </span>
      </div>
    );
  }

  const body =
    typeof decoded === "string" ? decoded : JSON.stringify(decoded, null, 2);
  const preview = body.replace(/\s+/g, " ").slice(0, 90);
  return (
    <details className="group px-3 py-1.5 text-xs">
      <summary className="flex cursor-pointer list-none items-baseline gap-3 [&::-webkit-details-marker]:hidden">
        <span className="flex w-2/5 shrink-0 items-baseline gap-1 font-mono break-all text-muted-foreground">
          <ChevronRight className="size-3 shrink-0 translate-y-0.5 transition-transform group-open:rotate-90" />
          {name}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground group-open:invisible">
          {redacted ? <RedactedTag /> : null}
          {preview}
        </span>
      </summary>
      <pre className="mt-1.5 max-h-80 overflow-auto rounded bg-surface-2 p-2 font-mono text-xs break-words whitespace-pre-wrap text-foreground">
        {body}
      </pre>
    </details>
  );
}

function RedactedTag() {
  return <span className="mr-1 text-chart-3">Redacted</span>;
}
