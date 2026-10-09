"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { ProjectOverview } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { mapPassRateBars } from "./map-overview";

const BarsInner = dynamic(
  () => import("./compare-bars-inner").then((m) => m.CompareBarsInner),
  {
    ssr: false,
    loading: () => (
      <div className="h-[160px] animate-pulse rounded-md bg-surface-2" aria-hidden />
    ),
  },
);

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

  const regressionOverflow = Math.max(
    0,
    overview.offline.regressions.length - (bars?.length ?? 0),
  );
  const barOverflow = bars ? Math.max(0, bars.length - 6) : 0;
  const moreCount = Math.max(barOverflow, regressionOverflow);

  return (
    <section
      aria-label="Pass rate compare"
      className="flex flex-col gap-2 rounded-md border border-border bg-surface p-3"
    >
      <h2 className="text-sm font-semibold text-foreground">Compare pass rate</h2>
      {bars == null || bars.length === 0 ? (
        <div className="flex flex-col gap-2 py-6 text-sm text-muted-foreground">
          <p>
            {latest
              ? "No baseline compare in this snapshot."
              : "Run an experiment to compare pass rates."}
          </p>
          {compareHref ? (
            <Link
              href={withProjectQuery(compareHref, projectId)}
              className="text-xs text-primary hover:underline"
            >
              Open compare
            </Link>
          ) : (
            <Link
              href={withProjectQuery("/experiments", projectId)}
              className="text-xs text-primary hover:underline"
            >
              Create run
            </Link>
          )}
        </div>
      ) : (
        <BarsInner
          bars={bars}
          projectId={projectId}
          compareHref={compareHref}
          moreCount={moreCount}
        />
      )}
    </section>
  );
}
