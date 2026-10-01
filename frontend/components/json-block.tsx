"use client";

import { useMemo, useState } from "react";
import { Copy, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const COLLAPSE_THRESHOLD = 4096;

type JsonBlockProps = {
  value: unknown;
  className?: string;
  label?: string;
};

function stringify(value: unknown): string {
  if (value === undefined) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function JsonBlock({ value, className, label }: JsonBlockProps) {
  const text = useMemo(() => stringify(value), [value]);
  const shouldCollapse = text.length > COLLAPSE_THRESHOLD;
  const [expanded, setExpanded] = useState(!shouldCollapse);

  const display =
    shouldCollapse && !expanded
      ? `${text.slice(0, COLLAPSE_THRESHOLD)}\n… (${text.length.toLocaleString()} chars)`
      : text;

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Could not copy");
    }
  }

  if (!text) {
    return (
      <p className="text-sm text-muted-foreground">—</p>
    );
  }

  return (
    <div className={cn("relative rounded-md border border-border bg-surface", className)}>
      <div className="flex items-center justify-between gap-2 border-b border-border px-2 py-1">
        {label ? (
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
        ) : (
          <span className="text-xs text-muted-foreground">JSON</span>
        )}
        <div className="flex items-center gap-1">
          {shouldCollapse ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="size-7"
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse" : "Expand"}
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded ? (
                <ChevronDown className="size-3.5" />
              ) : (
                <ChevronRight className="size-3.5" />
              )}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="size-7"
            aria-label="Copy JSON"
            onClick={onCopy}
          >
            <Copy className="size-3.5" />
          </Button>
        </div>
      </div>
      <pre className="max-h-[min(480px,50vh)] overflow-auto p-3 font-mono text-xs leading-relaxed text-foreground">
        {display}
      </pre>
    </div>
  );
}
