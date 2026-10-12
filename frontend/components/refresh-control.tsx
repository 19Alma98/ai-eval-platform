"use client";

import {
  useQuery,
  useQueryClient,
  type QueryFunction,
  type QueryKey,
} from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

export function RefreshControl({
  queryKey,
  queryFn,
  dataUpdatedAt: dataUpdatedAtProp,
  onRefresh,
  className,
}: {
  queryKey?: QueryKey;
  queryFn?: QueryFunction<unknown>;
  dataUpdatedAt?: number;
  onRefresh?: () => Promise<unknown>;
  className?: string;
}) {
  const client = useQueryClient();
  const boundToQuery =
    queryKey != null &&
    queryFn != null &&
    dataUpdatedAtProp === undefined &&
    onRefresh === undefined;

  const query = useQuery({
    queryKey: queryKey ?? ["__refresh_control_inert"],
    queryFn: queryFn ?? (async () => null),
    enabled: boundToQuery,
  });

  const [manualRefreshing, setManualRefreshing] = useState(false);
  const [fallbackUpdatedAt, setFallbackUpdatedAt] = useState<number | null>(
    null,
  );

  useEffect(() => {
    if (!queryKey || boundToQuery || dataUpdatedAtProp !== undefined) return;
    const sync = () => {
      const state = client.getQueryState(queryKey);
      if (state?.dataUpdatedAt) setFallbackUpdatedAt(state.dataUpdatedAt);
    };
    sync();
    const unsub = client.getQueryCache().subscribe((event) => {
      if (
        event.type === "updated" &&
        queryKey.every(
          (k, i) => (event.query.queryKey as unknown[])[i] === k,
        )
      ) {
        setFallbackUpdatedAt(event.query.state.dataUpdatedAt);
      }
    });
    return unsub;
  }, [boundToQuery, client, dataUpdatedAtProp, queryKey]);

  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const refreshing = onRefresh
    ? manualRefreshing
    : boundToQuery
      ? query.isFetching
      : manualRefreshing;

  const updatedAt = dataUpdatedAtProp ?? (boundToQuery
    ? query.dataUpdatedAt || null
    : fallbackUpdatedAt);

  async function handleRefresh() {
    if (onRefresh) {
      setManualRefreshing(true);
      try {
        await onRefresh();
      } finally {
        setManualRefreshing(false);
      }
      return;
    }
    setManualRefreshing(true);
    try {
      if (boundToQuery) {
        await query.refetch();
      } else if (queryKey) {
        await client.refetchQueries({ queryKey });
        const state = client.getQueryState(queryKey);
        setFallbackUpdatedAt(state?.dataUpdatedAt ?? Date.now());
      } else {
        await client.refetchQueries();
        setFallbackUpdatedAt(Date.now());
      }
    } finally {
      setManualRefreshing(false);
    }
  }

  const label =
    updatedAt != null && updatedAt > 0
      ? `Updated ${formatRelativeTime(new Date(updatedAt), new Date())}`
      : "Not loaded yet";

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={handleRefresh}
      disabled={refreshing}
      aria-label={`Refresh (${label.toLowerCase()})`}
      title={`${label} · click to refresh`}
      className={className}
    >
      <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
    </Button>
  );
}
