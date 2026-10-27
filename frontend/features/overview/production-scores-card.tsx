"use client";

import { Button } from "@/components/ui/button";
import { formatErrorForUi } from "@/lib/api/client";
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
  // Nothing logged yet: the live panel already says how to send traffic; an
  // empty card here would only repeat it.
  if (query.isSuccess && rows.length === 0) return null;
  return (
    <section
      aria-label="Production scores"
      className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-foreground">Production scores</h2>
      {query.isPending ? (
        <div
          className="h-16 animate-pulse rounded-md border border-border bg-surface-2"
          role="status"
          aria-label="Loading production scores"
        />
      ) : query.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-muted-foreground">
            Could not load production scores: {formatErrorForUi(query.error)}
          </p>
          <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </div>
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
