"use client";

import Link from "next/link";
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
              "rounded-md border border-border bg-surface p-3",
              c.status === "empty" && "border-dashed",
            )}
          >
            <p className="text-xs font-medium text-muted-foreground">{c.title}</p>
            <p className="mt-1 text-sm text-foreground">{c.summary}</p>
            <p className="mt-1 text-xs text-muted-foreground">{c.measure}</p>
            {showCta ? (
              <Link
                href={withProjectQuery(c.href, projectId)}
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
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
