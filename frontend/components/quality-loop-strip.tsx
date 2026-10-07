"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useProjectId } from "@/lib/project-store";
import { withProjectQuery } from "@/lib/project-href";
import { cn } from "@/lib/cn";

const STEPS = [
  {
    id: "datasets",
    label: "Test set",
    href: "/datasets",
    match: (p: string) => p.startsWith("/datasets"),
  },
  {
    id: "app-configs",
    label: "App configs",
    href: "/app-configs",
    match: (p: string) => p.startsWith("/app-configs"),
  },
  {
    id: "metrics",
    label: "Metriche",
    href: "/metrics",
    match: (p: string) => p.startsWith("/metrics"),
  },
  {
    id: "experiments",
    label: "Runs",
    href: "/experiments",
    match: (p: string) =>
      p.startsWith("/experiments") && !p.includes("/compare"),
  },
  {
    id: "compare",
    label: "Confronta",
    // resolved inside component when pathname has experimentId
    href: "/experiments",
    match: (p: string) => p.includes("/compare"),
  },
  {
    id: "release",
    label: "Release",
    href: "/release",
    match: (p: string) => p.startsWith("/release"),
  },
] as const;

export function QualityLoopStrip() {
  const pathname = usePathname();
  const { projectId } = useProjectId();
  const expMatch = pathname.match(/^\/experiments\/([^/]+)/);
  const experimentId = expMatch?.[1];

  return (
    <nav
      aria-label="Quality loop"
      className="mb-4 flex flex-wrap items-center gap-1 border-b border-border pb-3 text-xs"
    >
      {STEPS.map((step, i) => {
        const href =
          step.id === "compare" && experimentId
            ? `/experiments/${experimentId}/compare`
            : step.href;
        const active = step.match(pathname);
        return (
          <span key={step.id} className="flex items-center gap-1">
            {i > 0 ? (
              <span className="px-1 text-muted-foreground" aria-hidden>
                →
              </span>
            ) : null}
            <Link
              href={withProjectQuery(href, projectId)}
              className={cn(
                "rounded px-1.5 py-0.5 text-muted-foreground hover:text-foreground",
                active && "bg-row-selected font-medium text-foreground",
              )}
              aria-current={active ? "step" : undefined}
            >
              {step.label}
            </Link>
          </span>
        );
      })}
    </nav>
  );
}
