"use client";

import Link from "next/link";
import { ArrowRight, CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { StatusPanel as StatusPanelModel, StatusTone } from "./map-overview";

const TONE_ICON: Record<StatusTone, typeof CircleCheck> = {
  ok: CircleCheck,
  fail: CircleAlert,
  neutral: CircleDashed,
};

function StatusPanel({ panel, projectId }: { panel: StatusPanelModel; projectId: string }) {
  const Icon = TONE_ICON[panel.tone];
  return (
    <section
      aria-label={panel.eyebrow}
      className={cn(
        "relative flex flex-col gap-4 overflow-hidden rounded-xl border bg-surface p-5",
        panel.tone === "fail" && "border-status-fail/40",
        panel.tone === "ok" && "border-status-ok/40",
        panel.tone === "neutral" && "border-border",
      )}
    >
      {/* Tone stripe: the verdict reads before any number does. */}
      <span
        aria-hidden
        className={cn(
          "absolute inset-x-0 top-0 h-1",
          panel.tone === "fail" && "bg-status-fail",
          panel.tone === "ok" && "bg-status-ok",
          panel.tone === "neutral" && "bg-border",
        )}
      />
      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {panel.eyebrow}
        </p>
        <h2
          className={cn(
            "flex items-center gap-2 text-2xl font-semibold tracking-tight",
            panel.tone === "fail" && "text-status-fail",
            panel.tone === "ok" && "text-status-ok",
            panel.tone === "neutral" && "text-foreground",
          )}
        >
          <Icon className="size-6 shrink-0" aria-hidden />
          {panel.headline}
        </h2>
        <p className="text-sm text-muted-foreground">{panel.detail}</p>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border pt-4 sm:grid-cols-3">
        {panel.stats.map((stat) => {
          const body = (
            <>
              <dt className="text-xs text-muted-foreground">{stat.label}</dt>
              <dd className="truncate text-base font-semibold tabular-nums text-foreground">
                {stat.value}
              </dd>
            </>
          );
          return stat.href ? (
            <Link
              key={stat.label}
              href={withProjectQuery(stat.href, projectId)}
              className="flex min-w-0 flex-col gap-0.5 rounded-md hover:text-primary [&_dd]:hover:text-primary"
            >
              {body}
            </Link>
          ) : (
            <div key={stat.label} className="flex min-w-0 flex-col gap-0.5">
              {body}
            </div>
          );
        })}
      </dl>

      {panel.primary || panel.secondary ? (
        <div className="mt-auto flex flex-wrap items-center gap-2">
          {panel.primary ? (
            <Button
              nativeButton={false}
              render={<Link href={withProjectQuery(panel.primary.href, projectId)} />}
            >
              {panel.primary.label}
              <ArrowRight className="size-4" aria-hidden />
            </Button>
          ) : null}
          {panel.secondary ? (
            <Button
              variant="outline"
              nativeButton={false}
              render={<Link href={withProjectQuery(panel.secondary.href, projectId)} />}
            >
              {panel.secondary.label}
            </Button>
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
    <div className={cn("grid gap-4", release && "lg:grid-cols-2")}>
      {release ? <StatusPanel panel={release} projectId={projectId} /> : null}
      <StatusPanel panel={live} projectId={projectId} />
    </div>
  );
}
