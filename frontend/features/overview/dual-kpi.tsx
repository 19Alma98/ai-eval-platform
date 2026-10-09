"use client";

import Link from "next/link";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { DualKpiViewModel } from "./map-overview";

function KpiCell({
  label,
  value,
  href,
  projectId,
}: {
  label: string;
  value: string;
  href: string;
  projectId: string;
}) {
  return (
    <Link
      href={withProjectQuery(href, projectId)}
      className={cn(
        "rounded-md border border-border bg-surface px-3 py-2.5 transition-colors hover:bg-row-hover",
      )}
    >
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg tabular-nums text-foreground">
        {value}
      </p>
    </Link>
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
    <section aria-label="Key metrics" className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">Live</h2>
        <div
          className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
          style={{ gap: "var(--grid-gap, 8px)" }}
        >
          {model.live.map((item) => (
            <KpiCell
              key={item.label}
              label={item.label}
              value={item.value}
              href={item.href}
              projectId={projectId}
            />
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">Offline</h2>
        <div
          className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
          style={{ gap: "var(--grid-gap, 8px)" }}
        >
          {model.offline.map((item) => (
            <KpiCell
              key={item.label}
              label={item.label}
              value={item.value}
              href={item.href}
              projectId={projectId}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
