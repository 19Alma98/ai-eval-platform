"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { ProductionHeader } from "@/components/production-header";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { formatErrorForUi } from "@/lib/api/client";
import {
  listConversations,
  type ConversationSummary,
} from "@/lib/api/conversations";
import { metricLabel } from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";

export function ConversationList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const [search, setSearch] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const query = useQuery({
    queryKey: ["conversations", projectId, search],
    queryFn: () =>
      listConversations(projectId!, {
        search: search.trim() || undefined,
        limit: 100,
      }),
    enabled: Boolean(projectId),
  });

  const rows = query.data?.items ?? [];
  const sessionJudgesEnabled = query.data?.session_judges_enabled ?? true;

  const onRowActivate = useCallback(
    (row: ConversationSummary) => {
      router.push(
        withProjectQuery(`/conversations/${encodeURIComponent(row.session_id)}`, projectId),
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<ConversationSummary>[] = useMemo(
    () => [
      {
        id: "session",
        header: "Session",
        wrap: true,
        cell: (row) => <span className="font-mono text-sm">{row.session_id}</span>,
      },
      {
        id: "user",
        header: "User",
        cell: (row) => row.user_id ?? "—",
      },
      {
        id: "turns",
        header: "Turns",
        className: "tabular-nums",
        cell: (row) => row.turn_count,
      },
      {
        id: "last",
        header: "Last activity",
        cell: (row) => <RelativeTime date={row.last_activity_at} />,
      },
      {
        id: "status",
        header: "Session judge",
        cell: (row) =>
          row.judge_status ? (
            <Badge variant="secondary">{row.judge_status}</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: "fails",
        header: "Fails",
        wrap: true,
        cell: (row) =>
          row.failing_score_kinds.length ? (
            <span className="flex flex-wrap gap-1">
              {row.failing_score_kinds.map((kind) => (
                <Badge key={kind} variant="outline">
                  {metricLabel(kind)}
                </Badge>
              ))}
            </span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
    ],
    [],
  );

  if (!projectId) return <LoadingBlock className="min-h-[240px]" />;
  if (query.isPending) return <LoadingBlock className="min-h-[240px]" />;
  if (query.isError) {
    return (
      <ErrorState
        title="Could not load conversations"
        message={formatErrorForUi(query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }

  const metricsHref = withProjectQuery("/metrics", projectId);

  return (
    <div className="flex flex-col gap-4">
      <ProductionHeader active="conversations" />
      {!sessionJudgesEnabled ? (
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-muted-foreground">
          Session judges are off in the project default metrics set, so conversations
          stay open without scores. Enable query rewrite, conversation consistency, or
          resolution in{" "}
          <Link href={metricsHref} className="text-primary hover:underline">
            Metrics
          </Link>
          .
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by session id"
          className="max-w-sm"
        />
      </div>
      {rows.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          description="Call opengrade.set_session(conversation_id) in production so turns group here as a chat timeline."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.session_id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={onRowActivate}
          aria-label="Conversations"
        />
      )}
    </div>
  );
}
