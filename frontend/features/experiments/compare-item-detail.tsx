"use client";

import type { ReactNode } from "react";
import { JudgeClaimsTable } from "@/components/judge-claims-table";
import { StatusBadge } from "@/components/status-badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ItemComparisonRow, ItemSide } from "@/lib/api/types";
import { formatScore } from "@/lib/format";
import { CompareStatusCell } from "./compare-table";

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      <div className="max-h-[220px] overflow-auto rounded-md border border-border bg-surface px-3 py-2 text-sm whitespace-pre-wrap break-words text-foreground">
        {children}
      </div>
    </div>
  );
}

function SideColumn({ title, side }: { title: string; side: ItemSide }) {
  const invalid = side.metadata?.error_type === "judge_output_invalid";
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-foreground">{title}</span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatScore(side.score)}
          </span>
          {side.label ? <StatusBadge status={side.label} /> : null}
        </span>
      </div>
      <Block title="Answer">
        {asText(side.actual_output) || (
          <span className="text-muted-foreground">No answer</span>
        )}
      </Block>
      {side.explanation?.trim() || invalid ? (
        <Block title="Why this score">
          {invalid ? "The judge returned an invalid response. " : ""}
          {side.explanation?.trim()}
        </Block>
      ) : null}
      <JudgeClaimsTable metadata={side.metadata} title="Claims checked" />
    </div>
  );
}

type CompareItemDetailProps = {
  row: ItemComparisonRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  baselineLabel?: string;
  candidateLabel?: string;
};

export function CompareItemDetail({
  row,
  open,
  onOpenChange,
  baselineLabel = "Baseline",
  candidateLabel = "Candidate",
}: CompareItemDetailProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(90vh,800px)] flex-col gap-4 sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            Answer comparison
            {row ? <CompareStatusCell status={row.status} /> : null}
          </DialogTitle>
          <DialogDescription>
            The same question answered by the baseline and the candidate.
          </DialogDescription>
        </DialogHeader>
        {row ? (
          <ScrollArea className="max-h-[calc(min(90vh,800px)-8rem)] pr-3">
            <div className="flex flex-col gap-4 pb-2">
              <Block title="Question">{asText(row.input) || "—"}</Block>
              <Block title="Expected answer">{asText(row.expected_output) || "—"}</Block>
              <div className="grid gap-4 md:grid-cols-2">
                <SideColumn title={`Baseline · ${baselineLabel}`} side={row.baseline} />
                <SideColumn title={`Candidate · ${candidateLabel}`} side={row.candidate} />
              </div>
            </div>
          </ScrollArea>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
