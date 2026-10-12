"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { FlaskConical, Lock } from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { MetaItem, PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatErrorForUi } from "@/lib/api/client";
import type { DatasetItem } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { ImportDatasetDialog } from "./import-dataset-dialog";
import { datasetQueryOptions, useDataset } from "./use-datasets";

const PREVIEW_MAX = 96;

function valuePreview(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function truncatePreview(text: string, max = PREVIEW_MAX): string {
  if (text === "—") return text;
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function stringList(metadata: Record<string, unknown>, key: string): string[] {
  const raw = metadata[key];
  if (Array.isArray(raw)) {
    return raw.filter((v): v is string => typeof v === "string" && v.trim() !== "");
  }
  if (typeof raw === "string" && raw.trim()) {
    return raw
      .split("|")
      .map((v) => v.trim())
      .filter(Boolean);
  }
  return [];
}

function DocChips({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {ids.map((id) => (
        <Badge key={id} variant="outline" className="font-normal">
          {id}
        </Badge>
      ))}
    </span>
  );
}

function formatStringList(
  metadata: Record<string, unknown>,
  key: string,
): string {
  const raw = metadata[key];
  if (Array.isArray(raw)) {
    const ids = raw.filter((id): id is string => typeof id === "string");
    return ids.length > 0 ? ids.join(", ") : "—";
  }
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return "—";
}

type DatasetDetailViewProps = {
  projectId: string;
  datasetId: string;
};

export function DatasetDetailView({
  projectId,
  datasetId,
}: DatasetDetailViewProps) {
  const query = useDataset(datasetId);
  const queryOpts = datasetQueryOptions(datasetId);
  const [inputFilter, setInputFilter] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [importOpen, setImportOpen] = useState(false);

  const dataset = query.data;
  const items = useMemo(() => dataset?.items ?? [], [dataset?.items]);

  const filteredItems = useMemo(() => {
    const q = inputFilter.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) =>
      valuePreview(item.input).toLowerCase().includes(q),
    );
  }, [items, inputFilter]);

  const hasActual = items.some((item) => item.actual_output != null);
  const hasLiveOrigin = items.some((item) => Boolean(item.source_trace_id));
  const hasMustContain = items.some(
    (item) => formatStringList(item.metadata ?? {}, "must_contain") !== "—",
  );

  const columns: DataTableColumn<DatasetItem>[] = useMemo(() => {
    const out: DataTableColumn<DatasetItem>[] = [
      {
        id: "index",
        header: "#",
        headerClassName: "w-[48px]",
        className: "tabular-nums text-muted-foreground",
        cell: (row) => {
          const idx = filteredItems.findIndex((item) => item.id === row.id);
          return idx >= 0 ? idx + 1 : "—";
        },
      },
      {
        id: "input",
        header: "Question",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-foreground">
            {valuePreview(row.input)}
          </span>
        ),
      },
      {
        id: "expected",
        header: "Expected answer",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-muted-foreground">
            {valuePreview(row.expected_output)}
          </span>
        ),
      },
      {
        id: "expected_doc_ids",
        header: "Source documents",
        headerClassName: "w-[180px]",
        wrap: true,
        cell: (row) => <DocChips ids={stringList(row.metadata ?? {}, "expected_doc_ids")} />,
      },
    ];
    if (hasMustContain) {
      out.push({
        id: "must_contain",
        header: "Required phrases",
        headerClassName: "w-[180px]",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-muted-foreground">
            {formatStringList(row.metadata ?? {}, "must_contain")}
          </span>
        ),
      });
    }
    if (hasActual) {
      out.push({
        id: "actual",
        header: "Recorded answer",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-muted-foreground">
            {truncatePreview(valuePreview(row.actual_output))}
          </span>
        ),
      });
    }
    if (hasLiveOrigin) out.push({
      id: "origin",
      header: "Origin",
      headerClassName: "w-[120px]",
      cell: (row) =>
        row.source_trace_id ? (
          <Badge variant="secondary">Live traffic</Badge>
        ) : (
          <span className="text-muted-foreground">Imported</span>
        ),
    });
    return out;
  }, [filteredItems, hasActual, hasMustContain, hasLiveOrigin]);

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load test set"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!dataset) {
    return null;
  }

  const listHref = withProjectQuery("/datasets", projectId);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumbs={[{ label: "Test sets", href: listHref }, { label: dataset.name }]}
        title={dataset.name}
        badges={
          <>
            <Badge variant="outline">v{dataset.version}</Badge>
            {dataset.immutable ? (
              <Badge
                variant="secondary"
                title="Experiments were scored on this version. Importing questions creates a new version, so past results stay comparable."
              >
                <Lock className="size-3" />
                Locked
              </Badge>
            ) : null}
          </>
        }
        description={dataset.description || undefined}
        meta={
          <>
            <MetaItem label="Questions">{items.length}</MetaItem>
            <MetaItem label="Created">
              <RelativeTime date={dataset.created_at} />
            </MetaItem>
          </>
        }
        actions={
          <>
            <RefreshControl
              queryKey={queryOpts.queryKey}
              dataUpdatedAt={query.dataUpdatedAt}
            />
            <Button
              variant="outline"
              size="sm"
              nativeButton={false}
              render={
                <Link href={withProjectQuery(`/experiments?new=1&dataset=${encodeURIComponent(datasetId)}`, projectId)} />
              }
            >
              <FlaskConical className="size-4" />
              Run experiment
            </Button>
            <ImportDatasetDialog
              projectId={projectId}
              datasetId={datasetId}
              datasetName={dataset.name}
              taskType={dataset.task_type}
              open={importOpen}
              onOpenChange={setImportOpen}
            />
          </>
        }
        className="mb-0"
      />

      {items.length > 0 ? (
        <div>
          <label htmlFor="dataset-item-filter" className="sr-only">
            Search questions
          </label>
          <Input
            id="dataset-item-filter"
            type="search"
            placeholder="Search questions…"
            value={inputFilter}
            onChange={(e) => {
              setInputFilter(e.target.value);
              setSelectedIndex(0);
            }}
            className="max-w-md"
          />
        </div>
      ) : null}

      {items.length === 0 ? (
        <EmptyState
          title="This test set is empty"
          description="Import a CSV or JSON file with your questions, or add failing answers from Live traffic."
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button type="button" size="sm" onClick={() => setImportOpen(true)}>
                Import questions
              </Button>
              <Button
                variant="outline"
                size="sm"
                nativeButton={false}
                render={<Link href={withProjectQuery("/live-runs", projectId)} />}
              >
                Open live traffic
              </Button>
            </div>
          }
        />
      ) : filteredItems.length === 0 ? (
        <EmptyState
          title="No matches"
          description="No questions match your search."
        />
      ) : (
        <DataTable
          rows={filteredItems}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => {}}
          aria-label="Questions in this test set"
        />
      )}
    </div>
  );
}
