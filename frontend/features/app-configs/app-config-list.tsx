"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { formatErrorForUi } from "@/lib/api/client";
import type { AppConfig } from "@/lib/api/types";
import { useProjectId } from "@/lib/project-store";
import {
  appConfigsQueryOptions,
  useAppConfigAliases,
  useAppConfigs,
} from "./use-app-configs";

type FamilyRow = {
  name: string;
  latest: AppConfig;
  aliasLabels: string[];
};

function buildFamilyRows(
  configs: AppConfig[],
  aliasNamesByFamily: Map<string, string[]>,
): FamilyRow[] {
  const byName = new Map<string, AppConfig>();
  for (const config of configs) {
    const existing = byName.get(config.name);
    if (!existing || config.version > existing.version) {
      byName.set(config.name, config);
    }
  }
  return [...byName.entries()]
    .map(([name, latest]) => ({
      name,
      latest,
      aliasLabels: aliasNamesByFamily.get(name) ?? [],
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function AppConfigList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const configsQuery = useAppConfigs(projectId);
  const aliasesQuery = useAppConfigAliases(projectId);
  const queryOpts = projectId ? appConfigsQueryOptions(projectId) : null;
  const [selectedIndex, setSelectedIndex] = useState(0);

  const aliasNamesByFamily = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const alias of aliasesQuery.data ?? []) {
      const family = alias.app_config.name;
      const entry = map.get(family) ?? [];
      entry.push(`${alias.name} → v${alias.app_config.version}`);
      map.set(family, entry);
    }
    for (const [, labels] of map) {
      labels.sort((a, b) => a.localeCompare(b));
    }
    return map;
  }, [aliasesQuery.data]);

  const rows = useMemo(
    () => buildFamilyRows(configsQuery.data ?? [], aliasNamesByFamily),
    [configsQuery.data, aliasNamesByFamily],
  );

  const onRowActivate = useCallback(
    (row: FamilyRow) => {
      if (!projectId) return;
      router.push(
        `/app-configs/${encodeURIComponent(row.name)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<FamilyRow>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Name",
        cell: (row) => (
          <span className="font-medium text-foreground">{row.name}</span>
        ),
      },
      {
        id: "version",
        header: "Latest version",
        headerClassName: "w-[120px]",
        className: "tabular-nums text-muted-foreground",
        cell: (row) => `v${row.latest.version}`,
      },
      {
        id: "aliases",
        header: "Aliases (e.g. production)",
        cell: (row) =>
          row.aliasLabels.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {row.aliasLabels.map((label) => (
                <Badge key={label} variant="secondary">
                  {label}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: "created",
        header: "Last updated",
        headerClassName: "w-[140px]",
        cell: (row) => <RelativeTime date={row.latest.created_at} />,
      },
    ],
    [],
  );

  const loading = configsQuery.isLoading || aliasesQuery.isLoading;
  const error = configsQuery.error ?? aliasesQuery.error;

  if (loading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (error) {
    const err = error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load app configs"
        message={message}
        onRetry={() => {
          void configsQuery.refetch();
          void aliasesQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <PageIntro
        title="App configs"
        glossary="Versioned prompt, model and retrieval settings of your app. Link one to an experiment to know exactly what produced its results."
        actions={
          queryOpts ? (
            <RefreshControl
              queryKey={queryOpts.queryKey}
              dataUpdatedAt={configsQuery.dataUpdatedAt}
            />
          ) : null
        }
      />

      {rows.length === 0 ? (
        <EmptyState
          title="No app configs yet"
          description="Register your prompt, model and retrieval settings from code with client.app_configs.create_app_config(project_id, name, prompt=…, model=…). Every change creates a new version you can compare."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.name}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={onRowActivate}
          aria-label="App config families"
        />
      )}
    </div>
  );
}
