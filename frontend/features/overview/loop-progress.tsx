"use client";

import Link from "next/link";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import type { LoopCard } from "./map-overview";

/** The quality loop as four numbered steps; the first unfinished one carries the action. */
export function LoopProgress({
  projectId,
  cards,
}: {
  projectId: string;
  cards: LoopCard[];
}) {
  const firstEmptyIndex = cards.findIndex((c) => c.status === "empty");

  return (
    <ol aria-label="Quality loop progress" className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((c, index) => {
        const done = c.status === "ready";
        const current = index === firstEmptyIndex;
        return (
          <li
            key={c.title}
            className={cn(
              "flex flex-col gap-1.5 border-t-2 pt-3",
              done ? "border-status-ok" : current ? "border-foreground" : "border-border",
            )}
          >
            <span
              className={cn(
                "flex items-center gap-1.5 font-serif text-lg",
                done ? "text-status-ok" : current ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {done ? <Check className="size-4" aria-label="Done" /> : `${index + 1}.`}
              <span className={cn(!done && !current && "text-muted-foreground")}>{c.title}</span>
            </span>
            <p className="text-sm text-muted-foreground">{c.measure}</p>
            <p className="text-sm text-foreground">{c.summary}</p>
            {current ? (
              <Button
                size="sm"
                className="mt-2 self-start"
                nativeButton={false}
                render={<Link href={withProjectQuery(c.href, projectId)} />}
              >
                {c.cta}
              </Button>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
