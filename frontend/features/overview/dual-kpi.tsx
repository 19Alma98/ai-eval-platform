"use client";

import Link from "next/link";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { DualKpiItem, DualKpiViewModel } from "./map-overview";

function KpiCell({ item, projectId }: { item: DualKpiItem; projectId: string }) {
  return (
    <Link
      href={withProjectQuery(item.href, projectId)}
      title={item.hint}
      className="group flex flex-col gap-1 rounded-lg border border-border bg-surface px-4 py-3 transition-colors hover:border-primary/40 hover:bg-row-hover"
    >
      <p className="text-xs font-medium text-muted-foreground">{item.label}</p>
      <p
        className={cn(
          "truncate text-xl font-semibold tabular-nums text-foreground",
          item.tone === "fail" && "text-status-fail",
          item.tone === "ok" && "text-status-ok",
        )}
      >
        {item.value}
      </p>
      {item.hint ? (
        <p className="line-clamp-1 text-xs text-muted-foreground">{item.hint}</p>
      ) : null}
    </Link>
  );
}

function KpiGroup({
  title,
  description,
  items,
  projectId,
}: {
  title: string;
  description: string;
  items: DualKpiItem[];
  projectId: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <span className="text-xs text-muted-foreground">{description}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <KpiCell key={item.label} item={item} projectId={projectId} />
        ))}
      </div>
    </div>
  );
}

export function DualKpi({
  projectId,
  model,
}: {
  projectId: string;
  model: DualKpiViewModel;
}) {
  return (
    <section aria-label="Key metrics" className="flex flex-col gap-5">
      <KpiGroup
        title="Live"
        description="Real user traffic in the selected time range"
        items={model.live}
        projectId={projectId}
      />
      <KpiGroup
        title="Offline"
        description="Test sets and experiments before release"
        items={model.offline}
        projectId={projectId}
      />
    </section>
  );
}
