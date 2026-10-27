"use client";

import { Info } from "lucide-react";
import type { EvaluatorSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatPercent, formatScore } from "@/lib/format";
import { groupByMetricCategory, metricInfo } from "@/lib/metrics-catalog";
import { targetState } from "./metric-target";

/**
 * Metric results grouped by what they measure (answer quality, retrieval, performance).
 * Clicking a metric focuses the case list on answers that failed it.
 */
export function MetricScorecard({
  evaluators,
  focusedRunId,
  onFocus,
}: {
  evaluators: EvaluatorSummary[];
  focusedRunId: string | null;
  onFocus: (runId: string | null) => void;
}) {
  const groups = groupByMetricCategory(evaluators, (row) => row.evaluator_name);

  return (
    <div className="grid gap-x-8 gap-y-4 lg:grid-cols-2 xl:grid-cols-3">
      {groups.map((group) => (
        <section
          key={group.category}
          aria-label={group.label}
          className="flex flex-col border-t border-border pt-1"
        >
          <h3 className="px-2.5 py-2 text-[13px] font-medium text-muted-foreground">
            {group.label}
          </h3>
          <ul className="flex flex-col p-1.5">
            {group.rows.map((row) => {
              const info = metricInfo(row.evaluator_name);
              const state = targetState(row.status);
              const focused = focusedRunId === row.run_id;
              const passPct = Math.round((row.pass_rate ?? 0) * 100);
              const issues = [
                row.n_error > 0 ? `${row.n_error} error${row.n_error === 1 ? "" : "s"}` : null,
                row.n_skipped > 0 ? `${row.n_skipped} skipped` : null,
              ].filter(Boolean);
              return (
                <li key={row.run_id}>
                  <button
                    type="button"
                    onClick={() => onFocus(focused ? null : row.run_id)}
                    aria-pressed={focused}
                    title={
                      focused
                        ? "Show all answers"
                        : `Show answers that failed ${info.label}`
                    }
                    className={cn(
                      "flex w-full flex-col gap-1.5 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-row-hover",
                      focused && "bg-row-selected ring-1 ring-primary/40",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-foreground">
                          {info.label}
                        </span>
                        {info.description ? (
                          <span title={info.description} className="shrink-0">
                            <Info
                              className="size-3.5 text-muted-foreground"
                              aria-label={info.description}
                            />
                          </span>
                        ) : null}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 text-sm font-semibold tabular-nums",
                          state === "missed" ? "text-status-fail" : "text-foreground",
                        )}
                      >
                        {formatPercent(row.pass_rate)}
                        <span className="ml-1 text-xs font-normal text-muted-foreground">
                          passed
                        </span>
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          state === "missed" ? "bg-status-fail" : "bg-status-ok",
                        )}
                        style={{ width: `${passPct}%` }}
                      />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Avg. score {formatScore(row.mean_score)} · {row.n_scored} of{" "}
                        {row.n_items} answers scored
                      </span>
                      {issues.length > 0 ? (
                        <span className="font-medium text-status-warn">
                          {issues.join(" · ")}
                        </span>
                      ) : state === "missed" ? (
                        <span className="font-medium text-status-fail">Below target</span>
                      ) : state === "met" ? (
                        <span className="text-status-ok">Meets target</span>
                      ) : null}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
