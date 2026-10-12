"use client";

import { useEffect, useMemo, useState } from "react";
import { formatRelativeTime, formatTs, parseTimestamp } from "@/lib/format";
import { cn } from "@/lib/cn";

export function RelativeTime({
  date,
  className,
}: {
  date: Date | string;
  className?: string;
}) {
  const parsed = useMemo(() => parseTimestamp(date), [date]);
  const [label, setLabel] = useState(() =>
    formatRelativeTime(parsed, new Date()),
  );

  useEffect(() => {
    const tick = () => setLabel(formatRelativeTime(parsed, new Date()));
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, [parsed]);

  return (
    <time
      dateTime={parsed.toISOString()}
      title={formatTs(parsed)}
      className={cn("font-mono tabular-nums", className)}
    >
      {label}
    </time>
  );
}
