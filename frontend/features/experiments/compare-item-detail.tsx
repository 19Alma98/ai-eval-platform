"use client";

import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ItemComparisonRow } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import { CompareStatusCell } from "./compare-table";

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatScore(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

function formatDelta(value: number | null): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
}

function DetailBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <pre className="max-h-[240px] overflow-auto rounded-md border border-border bg-surface p-3 font-mono text-xs whitespace-pre-wrap break-words text-foreground">
        {children}
      </pre>
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
      <DialogContent className="flex max-h-[min(90vh,720px)] flex-col gap-4 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            Item{" "}
            <span className="font-mono text-sm font-normal text-muted-foreground">
              {row ? truncateId(row.dataset_item_id, 12) : "—"}
            </span>
            {row ? <CompareStatusCell status={row.status} /> : null}
          </DialogTitle>
          <DialogDescription>
            Full inputs, outputs, judge notes, and context for this case.
          </DialogDescription>
        </DialogHeader>
        {row ? (
          <ScrollArea className="max-h-[calc(min(90vh,720px)-8rem)] pr-3">
            <div className="flex flex-col gap-4 pb-2">
              <DetailBlock title="Input">{formatJson(row.input)}</DetailBlock>
              <DetailBlock title="Expected output">
                {formatJson(row.expected_output)}
              </DetailBlock>
              <div className="grid gap-4 sm:grid-cols-2">
                <DetailBlock title={`${baselineLabel} output`}>
                  {formatJson(row.baseline.actual_output)}
                </DetailBlock>
                <DetailBlock title={`${candidateLabel} output`}>
                  {formatJson(row.candidate.actual_output)}
                </DetailBlock>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <DetailBlock title={`${baselineLabel} score`}>
                  {formatScore(row.baseline.score)}
                  {row.baseline.label ? ` · ${row.baseline.label}` : ""}
                </DetailBlock>
                <DetailBlock title={`${candidateLabel} score`}>
                  {formatScore(row.candidate.score)}
                  {row.candidate.label ? ` · ${row.candidate.label}` : ""}
                </DetailBlock>
              </div>
              <p className="text-sm text-muted-foreground">
                Delta{" "}
                <span className="font-mono tabular-nums text-foreground">
                  {formatDelta(row.delta)}
                </span>
              </p>
              {row.baseline.explanation || row.candidate.explanation ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  <DetailBlock title={`${baselineLabel} explanation`}>
                    {row.baseline.explanation?.trim() || "—"}
                  </DetailBlock>
                  <DetailBlock title={`${candidateLabel} explanation`}>
                    {row.candidate.explanation?.trim() || "—"}
                  </DetailBlock>
                </div>
              ) : null}
              {row.baseline.context != null || row.candidate.context != null ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  <DetailBlock title={`${baselineLabel} context`}>
                    {formatJson(row.baseline.context)}
                  </DetailBlock>
                  <DetailBlock title={`${candidateLabel} context`}>
                    {formatJson(row.candidate.context)}
                  </DetailBlock>
                </div>
              ) : null}
            </div>
          </ScrollArea>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
