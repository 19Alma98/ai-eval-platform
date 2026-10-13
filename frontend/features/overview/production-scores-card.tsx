"use client";

import { productionScoreRows } from "./production-scores";
import { useTraceScoreSummary } from "./use-trace-score-summary";

export function ProductionScoresCard({
  projectId,
  since,
  until,
}: {
  projectId: string;
  since: string;
  until: string;
}) {
  const query = useTraceScoreSummary(projectId, since, until);
  const rows = productionScoreRows(query.data);
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-foreground">Production scores</h2>
      {query.isError ? (
        <p className="text-sm text-muted-foreground">Could not load production scores.</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No scores in this range. Send them with <code>aiobs.log_score</code>,{" "}
          <code>aiobs.log_feedback</code> or <code>@aiobs.trace(metrics=[...])</code>.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {rows.map((row) => (
            <li key={row.key} className="flex items-center justify-between gap-4 py-2 text-sm">
              <span className="font-medium text-foreground">{row.label}</span>
              <span className="flex items-center gap-3 tabular-nums text-muted-foreground">
                <span className="text-foreground">{row.primary}</span>
                {row.secondary ? <span>{row.secondary}</span> : null}
                <span>{row.count} scored</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
