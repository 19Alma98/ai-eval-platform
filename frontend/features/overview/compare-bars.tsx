"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { ProjectOverview } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDeltaPoints, formatPercent } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import { mapPassRateBars } from "./map-overview";

const MAX_ROWS = 6;

/** Latest experiment vs its baseline: pass rate per metric, worst change first. */
export function CompareBars({
  projectId,
  overview,
}: {
  projectId: string;
  overview: ProjectOverview;
}) {
  const bars = mapPassRateBars(overview);
  const compare = overview.offline.compare;
  const latest = overview.offline.latest_experiment;

  const compareHref =
    compare != null
      ? `/experiments/${encodeURIComponent(compare.candidate_experiment_id)}/compare?baseline=${encodeURIComponent(compare.baseline_experiment_id)}`
      : latest
        ? `/experiments/${encodeURIComponent(latest.id)}/compare`
        : null;

  const rows = [...(bars ?? [])].sort(
    (a, b) => (a.delta ?? 0) - (b.delta ?? 0),
  );

  return (
    <section
      aria-label="Latest experiment vs baseline"
      className="flex flex-col gap-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-serif text-lg font-medium text-foreground">
          Latest experiment vs baseline
        </h2>
        <span className="text-xs text-muted-foreground">Pass rate per metric</span>
      </div>
      {rows.length === 0 ? (
        <div className="flex flex-col gap-2 py-4 text-sm text-muted-foreground">
          <p>
            {latest
              ? "Pick a baseline experiment to see what improved and what got worse."
              : "Run an experiment to see pass rates here."}
          </p>
          <Link
            href={withProjectQuery(compareHref ?? "/experiments", projectId)}
            className="text-xs text-primary hover:underline"
          >
            {compareHref ? "Compare experiments" : "New experiment"}
          </Link>
        </div>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {rows.slice(0, MAX_ROWS).map((row) => {
              // Colour only significant changes; the overview API sends "regressed".
              const worse = row.status === "regressed";
              const better = row.status === "improved";
              return (
                <li key={row.name} className="flex items-center gap-3 text-sm">
                  <span className="w-40 shrink-0 truncate text-foreground">{row.name}</span>
                  <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className={cn(
                        "absolute inset-y-0 left-0 rounded-full",
                        worse ? "bg-status-fail" : "bg-primary",
                      )}
                      style={{ width: `${Math.round((row.candidate ?? 0) * 100)}%` }}
                    />
                    {row.baseline != null ? (
                      <div
                        className="absolute inset-y-[-2px] w-0.5 bg-foreground/60"
                        style={{ left: `calc(${Math.round(row.baseline * 100)}% - 1px)` }}
                        title={`Baseline ${formatPercent(row.baseline)}`}
                      />
                    ) : null}
                  </div>
                  <span className="w-12 shrink-0 text-right tabular-nums text-foreground">
                    {formatPercent(row.candidate)}
                  </span>
                  <span
                    className={cn(
                      "w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground",
                      worse && "font-medium text-status-fail",
                      better && "font-medium text-status-ok",
                    )}
                  >
                    {formatDeltaPoints(row.delta)}
                  </span>
                </li>
              );
            })}
          </ul>
          {compareHref ? (
            <Link
              href={withProjectQuery(compareHref, projectId)}
              className="inline-flex items-center gap-1 self-start text-xs text-primary hover:underline"
            >
              {rows.length > MAX_ROWS
                ? `See all ${rows.length} metrics`
                : "Open full comparison"}
              <ArrowRight className="size-3" />
            </Link>
          ) : null}
        </>
      )}
    </section>
  );
}
