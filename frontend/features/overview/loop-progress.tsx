"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { LoopCard } from "./map-overview";

export function LoopProgress({
  projectId,
  cards,
}: {
  projectId: string;
  cards: LoopCard[];
}) {
  const firstEmptyIndex = cards.findIndex((c) => c.status === "empty");

  return (
    <section
      aria-label="Quality loop progress"
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
    >
      {cards.map((c, index) => {
        const showCta = index === firstEmptyIndex;

        return (
          <div
            key={c.title}
            className={cn(
              "rounded-lg border border-border bg-surface p-4",
              c.status === "empty" && "border-dashed",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">{c.title}</p>
              {c.status === "ready" ? (
                <CheckCircle2 className="size-4 shrink-0 text-status-ok" aria-label="Done" />
              ) : null}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{c.measure}</p>
            <p className="mt-2 text-sm text-foreground">{c.summary}</p>
            {showCta ? (
              <Link
                href={withProjectQuery(c.href, projectId)}
                className={cn(
                  buttonVariants({ variant: "default", size: "sm" }),
                  "mt-3",
                )}
              >
                {c.cta}
              </Link>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
