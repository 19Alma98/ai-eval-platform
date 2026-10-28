"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { StatusPanel as StatusPanelModel } from "./map-overview";

function StatusPanel({ panel, projectId }: { panel: StatusPanelModel; projectId: string }) {
  return (
    <section aria-label={panel.eyebrow} className="flex flex-col gap-5 py-6 lg:px-8 lg:first:pl-0 lg:last:pr-0">
      <div className="flex flex-col gap-2">
        <p className="flex items-center gap-2 text-[13px] font-medium text-muted-foreground">
          <span
            aria-hidden
            className={cn(
              "size-2 rounded-full",
              panel.tone === "fail" && "bg-status-fail",
              panel.tone === "ok" && "bg-status-ok",
              panel.tone === "neutral" && "bg-status-unset/50",
            )}
          />
          {panel.eyebrow}
        </p>
        <h2
          className={cn(
            "font-serif text-[1.9rem] leading-[1.15] font-medium tracking-tight",
            panel.tone === "fail" && "text-status-fail",
            panel.tone === "ok" && "text-status-ok",
            panel.tone === "neutral" && "text-foreground",
          )}
        >
          {panel.headline}
        </h2>
        <p className="max-w-prose text-[15px] leading-relaxed text-muted-foreground">
          {panel.detail}
        </p>
      </div>

      <dl className="flex flex-wrap gap-x-8 gap-y-3">
        {panel.stats.map((stat) => {
          const body = (
            <>
              <dd className="order-1 text-xl font-medium tabular-nums text-foreground">
                {stat.value}
              </dd>
              <dt className="order-2 text-xs text-muted-foreground">{stat.label}</dt>
            </>
          );
          return stat.href ? (
            <Link
              key={stat.label}
              href={withProjectQuery(stat.href, projectId)}
              className="flex min-w-0 flex-col [&_dd]:decoration-border [&_dd]:underline-offset-4 hover:[&_dd]:underline"
            >
              {body}
            </Link>
          ) : (
            <div key={stat.label} className="flex min-w-0 flex-col">
              {body}
            </div>
          );
        })}
      </dl>

      {panel.primary || panel.secondary ? (
        <div className="mt-auto flex flex-wrap items-center gap-4">
          {panel.primary ? (
            <Button
              nativeButton={false}
              render={<Link href={withProjectQuery(panel.primary.href, projectId)} />}
            >
              {panel.primary.label}
            </Button>
          ) : null}
          {panel.secondary ? (
            <Link
              href={withProjectQuery(panel.secondary.href, projectId)}
              className="text-sm text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground"
            >
              {panel.secondary.label}
            </Link>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** The two questions the Overview answers first: is the next version safe, is production healthy? */
export function StatusPanels({
  projectId,
  release,
  live,
}: {
  projectId: string;
  /** Null while there is nothing to release yet: Getting started covers that. */
  release: StatusPanelModel | null;
  live: StatusPanelModel;
}) {
  return (
    <div
      className={cn(
        "grid border-y border-border",
        release && "lg:grid-cols-2 lg:divide-x lg:divide-border",
      )}
    >
      {release ? <StatusPanel panel={release} projectId={projectId} /> : null}
      <StatusPanel panel={live} projectId={projectId} />
    </div>
  );
}
