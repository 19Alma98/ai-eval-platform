"use client";

import Link from "next/link";
import { RelativeTime } from "@/components/relative-time";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { AttentionRow } from "./map-overview";

function kindLabel(kind: AttentionRow["kind"]): string {
  switch (kind) {
    case "live_fail":
      return "Live fail";
    case "regression":
      return "Regression";
    case "calibration":
      return "Calibration";
  }
}

export function AttentionQueue({
  projectId,
  rows,
}: {
  projectId: string;
  rows: AttentionRow[];
}) {
  if (rows.length === 0) {
    return (
      <section
        aria-label="Attention queue"
        className="flex flex-col gap-2 rounded-md border border-dashed border-border bg-surface p-3"
      >
        <h2 className="text-sm font-semibold text-foreground">Needs attention</h2>
        <p className="text-sm text-muted-foreground">No issues in this range.</p>
        <div className="flex flex-wrap gap-3 text-xs">
          <Link
            href={withProjectQuery("/live-runs", projectId)}
            className="text-primary hover:underline"
          >
            Open live runs
          </Link>
          <Link
            href={withProjectQuery("/experiments", projectId)}
            className="text-primary hover:underline"
          >
            Create run
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section
      aria-label="Attention queue"
      className="flex flex-col gap-2 rounded-md border border-border bg-surface p-3"
    >
      <h2 className="text-sm font-semibold text-foreground">Needs attention</h2>
      <ul className="divide-y divide-border">
        {rows.map((row) => {
          const content = (
            <>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-muted-foreground">
                  {kindLabel(row.kind)}
                </span>
                {row.createdAt ? (
                  <RelativeTime date={row.createdAt} className="text-xs" />
                ) : null}
              </div>
              <p className="mt-0.5 text-sm font-medium text-foreground">{row.title}</p>
              {row.subtitle ? (
                <p className="text-xs text-muted-foreground">{row.subtitle}</p>
              ) : null}
            </>
          );

          if (row.href) {
            return (
              <li key={row.id}>
                <Link
                  href={withProjectQuery(row.href, projectId)}
                  className={cn(
                    "block py-2 transition-colors hover:bg-row-hover",
                  )}
                >
                  {content}
                </Link>
              </li>
            );
          }

          return (
            <li key={row.id} className="py-2">
              {content}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
