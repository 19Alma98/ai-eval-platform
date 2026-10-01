"use client";

import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

export function RefreshControl({
  queryKey,
  className,
}: {
  queryKey?: readonly unknown[];
  className?: string;
}) {
  const client = useQueryClient();
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!queryKey) return;
    const state = client.getQueryState(queryKey);
    if (state?.dataUpdatedAt) setUpdatedAt(state.dataUpdatedAt);
    const unsub = client.getQueryCache().subscribe((event) => {
      if (
        event.type === "updated" &&
        queryKey.every(
          (k, i) => (event.query.queryKey as unknown[])[i] === k,
        )
      ) {
        setUpdatedAt(event.query.state.dataUpdatedAt);
      }
    });
    return unsub;
  }, [client, queryKey]);

  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      if (queryKey) {
        await client.refetchQueries({ queryKey });
        const state = client.getQueryState(queryKey);
        setUpdatedAt(state?.dataUpdatedAt ?? Date.now());
      } else {
        await client.refetchQueries();
        setUpdatedAt(Date.now());
      }
    } finally {
      setRefreshing(false);
    }
  }

  const label =
    updatedAt != null
      ? `Updated ${formatRelativeTime(new Date(updatedAt), new Date())}`
      : "Not loaded yet";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={handleRefresh}
        disabled={refreshing}
        aria-label="Refresh data"
      >
        <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
      </Button>
    </div>
  );
}
