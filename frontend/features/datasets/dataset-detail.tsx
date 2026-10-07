"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import type { DatasetItem } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { ImportDatasetDialog } from "./import-dataset-dialog";
import { RAG_FIELD_HINTS } from "./rag-qa";
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
  const items = dataset?.items ?? [];

  const filteredItems = useMemo(() => {
    const q = inputFilter.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) =>
      valuePreview(item.input).toLowerCase().includes(q),
    );
  }, [items, inputFilter]);

  const columns: DataTableColumn<DatasetItem>[] = useMemo(
    () => [
      {
        id: "index",
        header: "#",
        headerClassName: "w-[48px]",
        className: "font-mono tabular-nums text-muted-foreground",
        cell: (row) => {
          const idx = filteredItems.findIndex((item) => item.id === row.id);
          return idx >= 0 ? idx + 1 : "—";
        },
      },
      {
        id: "input",
        header: "Input preview",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-foreground">
            {truncatePreview(valuePreview(row.input))}
          </span>
        ),
      },
      {
        id: "expected",
        header: "Expected",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(valuePreview(row.expected_output))}
          </span>
        ),
      },
      {
        id: "expected_doc_ids",
        header: "Expected doc IDs",
        headerClassName: "w-[160px]",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(
              formatStringList(row.metadata ?? {}, "expected_doc_ids"),
            )}
          </span>
        ),
      },
      {
        id: "must_contain",
        header: "Must contain",
        headerClassName: "w-[160px]",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(
              formatStringList(row.metadata ?? {}, "must_contain"),
            )}
          </span>
        ),
      },
      {
        id: "actual",
        header: "Actual",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(valuePreview(row.actual_output))}
          </span>
        ),
      },
      {
        id: "source_trace",
        header: "Source trace",
        headerClassName: "w-[112px]",
        cell: (row) =>
          row.source_trace_id ? (
            <Link
              href={withProjectQuery(
                `/traces/${encodeURIComponent(row.source_trace_id)}`,
                projectId,
              )}
              className="text-xs font-medium text-primary hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              View trace
            </Link>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
    ],
    [filteredItems, projectId],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Could not load dataset"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!dataset) {
    return null;
  }

  const backHref = withProjectQuery("/datasets", projectId);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href={backHref} />}
            >
              <ArrowLeft className="size-4" />
              Back
            </Button>
            <h1 className="text-lg font-semibold text-foreground">
              {dataset.name}
            </h1>
            <span className="rounded-md border border-border bg-surface px-2 py-0.5 font-mono text-xs text-muted-foreground">
              v{dataset.version}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {dataset.description ? (
              <span className="max-w-xl">{dataset.description}</span>
            ) : null}
            <span>
              Items{" "}
              <span className="font-mono tabular-nums text-foreground">
                {items.length}
              </span>
            </span>
            <span>
              Created <RelativeTime date={dataset.created_at} />
            </span>
          </div>
          <div className="mt-1 max-w-2xl rounded-md border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
            <p className="mb-1 font-medium text-foreground">
              Suggested item fields
            </p>
            <ul className="list-inside list-disc">
              {RAG_FIELD_HINTS.map((hint) => (
                <li key={hint}>{hint}</li>
              ))}
            </ul>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ImportDatasetDialog
            projectId={projectId}
            datasetId={datasetId}
            datasetName={dataset.name}
            taskType={dataset.task_type}
            open={importOpen}
            onOpenChange={setImportOpen}
          />
          <RefreshControl
            queryKey={queryOpts.queryKey}
            dataUpdatedAt={query.dataUpdatedAt}
          />
        </div>
      </div>

      <div className="sticky top-0 z-20 -mx-1 border-b border-border bg-background px-1 pb-3">
        <label htmlFor="dataset-item-filter" className="sr-only">
          Filter by input preview
        </label>
        <Input
          id="dataset-item-filter"
          type="search"
          placeholder="Filter items by input text…"
          value={inputFilter}
          onChange={(e) => {
            setInputFilter(e.target.value);
            setSelectedIndex(0);
          }}
          className="max-w-md"
        />
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="No items in this dataset"
          description="Promote a production or demo trace into an evaluation example."
          action={
            <Link
              href={withProjectQuery("/traces", projectId)}
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              Open traces
            </Link>
          }
        />
      ) : filteredItems.length === 0 ? (
        <EmptyState
          title="No matches"
          description="No items match the input filter."
        />
      ) : (
        <DataTable
          rows={filteredItems}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => {}}
          aria-label="Dataset items"
        />
      )}
    </div>
  );
}
