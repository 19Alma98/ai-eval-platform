"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown, GitCompare } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageHeader } from "@/components/page-header";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDatasets } from "@/features/datasets/use-datasets";
import { formatErrorForUi } from "@/lib/api/client";
import { summarizeProjectExperiments } from "@/lib/api/experiments";
import { cn } from "@/lib/cn";
import { formatPercent, formatScore } from "@/lib/format";
import { experimentHref } from "@/lib/links";
import { metricLabel } from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import {
  bestByColumn,
  buildMatrix,
  filterRows,
  sortRows,
  trendSeries,
  varyingParams,
  type MatrixFilters,
  type MatrixRow,
  type MetricColumn,
  type SortState,
} from "./experiment-matrix";
import { useExperiments } from "./use-experiments";

const TrendChart = dynamic(
  () => import("./metric-trend-chart-inner").then((m) => m.MetricTrendChartInner),
  {
    ssr: false,
    loading: () => <div className="h-[240px] animate-pulse rounded-md bg-surface-2" aria-hidden />,
  },
);

const ALL = "__all__";

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | null;
  options: { value: string; label: string }[];
  onChange: (value: string | null) => void;
}) {
  return (
    <Select value={value ?? ALL} onValueChange={(v) => onChange(!v || v === ALL ? null : v)}>
      <SelectTrigger className="h-8 min-w-[140px] text-xs" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL} className="text-xs">
          {`Any ${label.toLowerCase()}`}
        </SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value} className="text-xs">
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  className,
}: {
  label: string;
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sort.key === sortKey;
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn("px-3 py-2 text-left text-xs font-medium text-muted-foreground", className)}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 whitespace-nowrap hover:text-foreground"
      >
        {label}
        <Icon className={cn("size-3", !active && "opacity-40")} aria-hidden />
      </button>
    </th>
  );
}

function uniqueOptions(values: (string | null)[]) {
  return [...new Set(values.filter((v): v is string => Boolean(v)))]
    .sort()
    .map((v) => ({ value: v, label: v }));
}

export function ExperimentsMatrixView({ projectId }: { projectId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const pinnedIds = useMemo(
    () => (searchParams.get("ids") ?? "").split(",").filter(Boolean),
    [searchParams],
  );
  const experimentsQuery = useExperiments(projectId);
  const datasetsQuery = useDatasets(projectId);
  const summariesQuery = useQuery({
    queryKey: ["experiment-summaries", projectId, pinnedIds.join(",")],
    queryFn: () => summarizeProjectExperiments(projectId, pinnedIds),
  });

  const [sort, setSort] = useState<SortState>({ key: "created", dir: "desc" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [trendMetric, setTrendMetric] = useState<string | null>(null);

  const filters: MatrixFilters = useMemo(() => {
    const rawParam = searchParams.get("param") ?? "";
    const eq = rawParam.indexOf("=");
    return {
      model: searchParams.get("model"),
      prompt: searchParams.get("prompt"),
      datasetId: searchParams.get("dataset"),
      param: eq > 0 ? { key: rawParam.slice(0, eq), value: rawParam.slice(eq + 1) } : null,
    };
  }, [searchParams]);

  const setParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value == null) params.delete(key);
      else params.set(key, value);
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const { rows: allRows, columns } = useMemo(() => {
    const experiments = (experimentsQuery.data ?? []).filter(
      (e) => pinnedIds.length === 0 || pinnedIds.includes(e.id),
    );
    return buildMatrix(experiments, summariesQuery.data ?? []);
  }, [experimentsQuery.data, pinnedIds, summariesQuery.data]);

  const rows = useMemo(
    () => sortRows(filterRows(allRows, filters), sort),
    [allRows, filters, sort],
  );
  const best = useMemo(() => bestByColumn(rows, columns), [rows, columns]);
  const params = useMemo(() => varyingParams(allRows), [allRows]);
  const datasetNames = useMemo(
    () => new Map((datasetsQuery.data ?? []).map((d) => [d.id, `${d.name} · v${d.version}`])),
    [datasetsQuery.data],
  );
  const trendColumns: MetricColumn[] = useMemo(() => {
    const evaluatorCols = columns.filter((c) => c.kind === "evaluator");
    if (trendMetric) return evaluatorCols.filter((c) => c.key === trendMetric);
    return evaluatorCols.slice(0, 6);
  }, [columns, trendMetric]);
  const trend = useMemo(() => trendSeries(rows, trendColumns), [rows, trendColumns]);

  function onSort(key: string) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "name" ? "asc" : "desc" },
    );
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const selectedRows = allRows.filter((r) => selected.has(r.experiment.id));
  const pairHref = (() => {
    if (selectedRows.length !== 2) return null;
    const [older, newer] = [...selectedRows].sort(
      (a, b) =>
        new Date(a.experiment.created_at).getTime() - new Date(b.experiment.created_at).getTime(),
    );
    return withProjectQuery(
      `/experiments/${encodeURIComponent(newer.experiment.id)}/compare?baseline=${encodeURIComponent(older.experiment.id)}`,
      projectId,
    );
  })();

  const loading = experimentsQuery.isLoading || summariesQuery.isLoading;
  const error = experimentsQuery.error ?? summariesQuery.error;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumbs={[
          { label: "Experiments", href: withProjectQuery("/experiments", projectId) },
          { label: "Compare" },
        ]}
        title="Compare experiments"
        description="Every experiment side by side, one column per metric. Sort by a metric, filter by model, prompt or any parameter, and pick two to see which questions got better or worse."
        actions={
          <>
            {selected.size > 0 ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setParam("ids", [...selected].join(","));
                  setSelected(new Set());
                }}
              >
                Show only selected ({selected.size})
              </Button>
            ) : null}
            {pinnedIds.length > 0 ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setParam("ids", null)}>
                Show all experiments
              </Button>
            ) : null}
            <Button
              size="sm"
              disabled={!pairHref}
              title={pairHref ? undefined : "Select exactly two experiments"}
              render={pairHref ? <Link href={pairHref} /> : undefined}
            >
              <GitCompare className="size-4" />
              Question-by-question diff
            </Button>
          </>
        }
        className="mb-0"
      />

      <div className="flex flex-wrap items-center gap-2">
        <FilterSelect
          label="Model"
          value={filters.model ?? null}
          options={uniqueOptions(allRows.map((r) => r.model))}
          onChange={(v) => setParam("model", v)}
        />
        <FilterSelect
          label="Prompt"
          value={filters.prompt ?? null}
          options={uniqueOptions(allRows.map((r) => r.prompt))}
          onChange={(v) => setParam("prompt", v)}
        />
        <FilterSelect
          label="Test set"
          value={filters.datasetId ?? null}
          options={[...new Set(allRows.map((r) => r.experiment.dataset_id))].map((id) => ({
            value: id,
            label: datasetNames.get(id) ?? "Test set",
          }))}
          onChange={(v) => setParam("dataset", v)}
        />
        {Object.keys(params).length > 0 ? (
          <FilterSelect
            label="Parameter"
            value={searchParams.get("param")}
            options={Object.entries(params).flatMap(([key, values]) =>
              values.map((value) => ({ value: `${key}=${value}`, label: `${key} = ${value}` })),
            )}
            onChange={(v) => setParam("param", v)}
          />
        ) : null}
        <span className="text-xs text-muted-foreground">
          {rows.length} of {allRows.length} experiments
        </span>
      </div>

      {loading ? (
        <LoadingBlock className="min-h-[240px]" />
      ) : error ? (
        <ErrorState
          title="Could not load experiments"
          message={formatErrorForUi(error)}
          onRetry={() => {
            void experimentsQuery.refetch();
            void summariesQuery.refetch();
          }}
        />
      ) : allRows.length === 0 ? (
        <EmptyState
          title="No experiments yet"
          description="Run your app on a test set first; each run becomes a row here."
        />
      ) : (
        <>
          <div className="overflow-auto rounded-lg border border-border bg-surface">
            <table className="w-full border-collapse text-sm" aria-label="Experiments by metric">
              <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_0_hsl(var(--border))]">
                <tr>
                  <th scope="col" className="w-8 px-3 py-2">
                    <span className="sr-only">Select</span>
                  </th>
                  <SortHeader label="Experiment" sortKey="name" sort={sort} onSort={onSort} />
                  <th scope="col" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                    Model
                  </th>
                  <th scope="col" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                    Prompt
                  </th>
                  {filters.param ? (
                    <th scope="col" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                      {filters.param.key}
                    </th>
                  ) : null}
                  <SortHeader label="Created" sortKey="created" sort={sort} onSort={onSort} />
                  {columns.map((col) => (
                    <SortHeader
                      key={col.key}
                      label={col.kind === "logged" ? col.label : metricLabel(col.label)}
                      sortKey={col.key}
                      sort={sort}
                      onSort={onSort}
                      className="text-right"
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <MatrixTableRow
                    key={row.experiment.id}
                    row={row}
                    columns={columns}
                    best={best}
                    projectId={projectId}
                    paramKey={filters.param?.key ?? null}
                    checked={selected.has(row.experiment.id)}
                    onToggle={() => toggle(row.experiment.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {trendColumns.length > 0 && rows.length > 1 ? (
            <section
              aria-label="Metrics across versions"
              className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">Metrics across versions</h2>
                <span className="text-xs text-muted-foreground">oldest to newest</span>
                <span className="flex-1" />
                <FilterSelect
                  label="Metric"
                  value={trendMetric}
                  options={columns
                    .filter((c) => c.kind === "evaluator")
                    .map((c) => ({ value: c.key, label: metricLabel(c.label) }))}
                  onChange={setTrendMetric}
                />
              </div>
              <TrendChart
                data={trend}
                columns={trendColumns.map((c) => ({ ...c, label: metricLabel(c.label) }))}
              />
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

function MatrixTableRow({
  row,
  columns,
  best,
  projectId,
  paramKey,
  checked,
  onToggle,
}: {
  row: MatrixRow;
  columns: MetricColumn[];
  best: Record<string, number>;
  projectId: string;
  paramKey: string | null;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <tr className={cn("border-b border-border last:border-b-0 hover:bg-row-hover", checked && "bg-row-selected")}>
      <td className="px-3 py-2">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={checked}
          onChange={onToggle}
          aria-label={`Select ${row.label}`}
        />
      </td>
      <td className="max-w-[260px] px-3 py-2">
        <Link
          href={experimentHref(projectId, row.experiment.id)}
          className="flex min-w-0 flex-col hover:text-primary"
        >
          <span className="truncate font-medium">{row.label}</span>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {row.label !== row.experiment.name ? (
              <span className="truncate">{row.experiment.name}</span>
            ) : null}
            <StatusBadge status={row.experiment.status} kind="experiment" />
          </span>
        </Link>
      </td>
      <td className="px-3 py-2 text-muted-foreground">{row.model ?? "—"}</td>
      <td className="px-3 py-2 text-muted-foreground">{row.prompt ?? "—"}</td>
      {paramKey ? (
        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
          {row.params[paramKey] ?? "—"}
        </td>
      ) : null}
      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
        <RelativeTime date={row.experiment.created_at} />
      </td>
      {columns.map((col) => {
        const cell = row.metrics[col.key];
        const isBest = cell?.mean != null && best[col.key] === cell.mean;
        return (
          <td
            key={col.key}
            className="px-3 py-2 text-right tabular-nums"
            title={
              cell && col.kind === "evaluator"
                ? `${cell.nScored} scored · ${formatPercent(cell.passRate)} pass`
                : undefined
            }
          >
            {cell?.mean != null ? (
              <span className={cn(isBest && "font-semibold text-status-ok")}>
                {col.kind === "logged" ? Number(cell.mean.toFixed(4)) : formatScore(cell.mean)}
              </span>
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
            {cell?.passRate != null ? (
              <span className="ml-1 text-xs text-muted-foreground">{formatPercent(cell.passRate)}</span>
            ) : null}
          </td>
        );
      })}
    </tr>
  );
}
