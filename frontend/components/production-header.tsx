"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";

export type ProductionTab = "health" | "answers" | "traces" | "alerts";

export const PRODUCTION_TABS: { id: ProductionTab; href: string; label: string; blurb: string }[] = [
  {
    id: "health",
    href: "/monitoring",
    label: "Health",
    blurb: "Latency, cost and answer quality over time, with alarms and a review queue.",
  },
  {
    id: "answers",
    href: "/live-runs",
    label: "Live answers",
    blurb: "Real questions scored by the LLM judge. Review verdicts and turn failures into test cases.",
  },
  {
    id: "traces",
    href: "/traces",
    label: "Traces",
    blurb: "Every call step by step: what was retrieved, what the model saw and what it answered.",
  },
  {
    id: "alerts",
    href: "/alerts",
    label: "Alerts",
    blurb: "Rules the server checks every minute; it notifies a webhook (Slack or any URL) when one fires.",
  },
];

export const PRODUCTION_PATHS = PRODUCTION_TABS.map((t) => t.href);

export function ProductionHeader({ active, actions }: { active: ProductionTab; actions?: ReactNode }) {
  const { projectId } = useProjectId();
  const current = PRODUCTION_TABS.find((t) => t.id === active)!;
  return (
    <div className="mb-5 flex flex-col gap-4">
      <PageHeader title="Production" description={current.blurb} actions={actions} className="mb-0" />
      <nav aria-label="Production views" className="-mb-px flex gap-6 border-b border-border">
        {PRODUCTION_TABS.map((tab) => (
          <Link
            key={tab.id}
            href={withProjectQuery(tab.href, projectId)}
            aria-current={tab.id === active ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 border-transparent pb-2 text-sm text-muted-foreground transition-colors hover:text-foreground",
              tab.id === active && "border-foreground font-medium text-foreground",
            )}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
