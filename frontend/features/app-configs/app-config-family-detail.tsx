"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Trash2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatErrorForUi } from "@/lib/api/client";
import { deleteAlias, setAlias } from "@/lib/api/app-configs";
import type { AppConfig, AppConfigAlias } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { formatConfigValue } from "./format-config-value";
import {
  appConfigAliasesQueryKey,
  appConfigVersionsQueryOptions,
  useAppConfigAliases,
  useAppConfigVersions,
} from "./use-app-configs";

const PRESET_ALIASES = ["prod", "baseline", "candidate"] as const;

function DetailBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <div className="max-h-[min(320px,40vh)] overflow-auto rounded-md border border-border bg-surface p-3 text-sm whitespace-pre-wrap break-words text-foreground">
        {children}
      </div>
    </div>
  );
}

function configPlainSnapshot(config: AppConfig): string {
  const parts = [
    `version: ${config.version}`,
    config.description?.trim()
      ? `description\n${config.description.trim()}`
      : null,
    `prompt\n${formatConfigValue(config.prompt)}`,
    `model\n${formatConfigValue(config.model)}`,
    `retrieval\n${formatConfigValue(config.retrieval)}`,
    `content_hash: ${config.content_hash}`,
  ];
  return parts.filter(Boolean).join("\n\n");
}

type AppConfigFamilyDetailProps = {
  projectId: string;
  familyName: string;
};

export function AppConfigFamilyDetail({
  projectId,
  familyName,
}: AppConfigFamilyDetailProps) {
  const queryClient = useQueryClient();
  const versionsQuery = useAppConfigVersions(projectId, familyName);
  const aliasesQuery = useAppConfigAliases(projectId);
  const queryOpts = appConfigVersionsQueryOptions(projectId, familyName);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [compareA, setCompareA] = useState<string>("");
  const [compareB, setCompareB] = useState<string>("");
  const [aliasPreset, setAliasPreset] = useState<string>("prod");
  const [customAlias, setCustomAlias] = useState("");
  const [aliasVersionId, setAliasVersionId] = useState<string>("");

  const versions = useMemo(() => {
    const list = versionsQuery.data ?? [];
    return [...list].sort((a, b) => b.version - a.version);
  }, [versionsQuery.data]);

  const familyAliases = useMemo(
    () =>
      (aliasesQuery.data ?? []).filter(
        (a) => a.app_config.name === familyName,
      ),
    [aliasesQuery.data, familyName],
  );

  const versionById = useMemo(() => {
    const map = new Map<string, AppConfig>();
    for (const v of versions) map.set(v.id, v);
    return map;
  }, [versions]);

  const configA = compareA ? versionById.get(compareA) : undefined;
  const configB = compareB ? versionById.get(compareB) : undefined;
  const selectedVersion = versions[selectedIndex] ?? versions[0];

  const setAliasMutation = useMutation({
    mutationFn: ({
      aliasName,
      appConfigId,
    }: {
      aliasName: string;
      appConfigId: string;
    }) => setAlias(projectId, aliasName, appConfigId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: appConfigAliasesQueryKey(projectId),
      });
      toast.success("Alias updated");
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
      toast.error(message);
    },
  });

  const deleteAliasMutation = useMutation({
    mutationFn: (aliasName: string) => deleteAlias(projectId, aliasName),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: appConfigAliasesQueryKey(projectId),
      });
      toast.success("Alias removed");
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
      toast.error(message);
    },
  });

  const columns: DataTableColumn<AppConfig>[] = useMemo(
    () => [
      {
        id: "version",
        header: "Version",
        headerClassName: "w-[88px]",
        className: "font-mono tabular-nums",
        cell: (row) => `v${row.version}`,
      },
      {
        id: "hash",
        header: "Hash",
        headerClassName: "w-[120px]",
        cell: (row) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.content_hash.slice(0, 12)}…
          </span>
        ),
      },
      {
        id: "description",
        header: "Description",
        cell: (row) => (
          <span className="line-clamp-2 text-sm text-muted-foreground">
            {row.description?.trim() || "—"}
          </span>
        ),
      },
      {
        id: "created",
        header: "Created",
        headerClassName: "w-[120px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
    ],
    [],
  );

  const loading = versionsQuery.isLoading || aliasesQuery.isLoading;
  const error = versionsQuery.error ?? aliasesQuery.error;

  if (loading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (error) {
    const err = error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load config family"
        message={message}
        onRetry={() => {
          void versionsQuery.refetch();
          void aliasesQuery.refetch();
        }}
      />
    );
  }

  const backHref = withProjectQuery("/app-configs", projectId);
  const effectiveAlias =
    aliasPreset === "custom" ? customAlias.trim() : aliasPreset;

  function handleSetAlias() {
    if (!effectiveAlias || !aliasVersionId) return;
    setAliasMutation.mutate({
      aliasName: effectiveAlias,
      appConfigId: aliasVersionId,
    });
  }

  return (
    <div className="flex flex-col gap-4">
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
              {familyName}
            </h1>
            <span className="rounded-md border border-border bg-surface px-2 py-0.5 font-mono text-xs text-muted-foreground">
              {versions.length} version{versions.length === 1 ? "" : "s"}
            </span>
          </div>
          {familyAliases.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Aliases:</span>
              {familyAliases.map((a) => (
                <AliasChip
                  key={a.name}
                  alias={a}
                  onDelete={() => deleteAliasMutation.mutate(a.name)}
                  deleting={deleteAliasMutation.isPending}
                />
              ))}
            </div>
          ) : null}
        </div>
        <RefreshControl
          queryKey={queryOpts.queryKey}
          dataUpdatedAt={versionsQuery.dataUpdatedAt}
        />
      </div>

      <section className="rounded-md border border-border bg-surface p-3">
        <h2 className="mb-3 text-sm font-medium text-foreground">Set alias</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-[160px]">
            <label className="mb-1 block text-xs text-muted-foreground">
              Alias
            </label>
            <Select
              value={aliasPreset}
              onValueChange={(v) => setAliasPreset(v ?? "prod")}
            >
              <SelectTrigger aria-label="Alias preset">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESET_ALIASES.map((a) => (
                  <SelectItem key={a} value={a}>
                    {a}
                  </SelectItem>
                ))}
                <SelectItem value="custom">Custom…</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {aliasPreset === "custom" ? (
            <div className="w-[180px]">
              <label
                htmlFor="custom-alias"
                className="mb-1 block text-xs text-muted-foreground"
              >
                Custom name
              </label>
              <Input
                id="custom-alias"
                value={customAlias}
                onChange={(e) => setCustomAlias(e.target.value)}
                placeholder="staging"
              />
            </div>
          ) : null}
          <div className="w-[160px]">
            <label className="mb-1 block text-xs text-muted-foreground">
              Points to version
            </label>
            <Select
              value={aliasVersionId}
              onValueChange={(v) => setAliasVersionId(v ?? "")}
            >
              <SelectTrigger aria-label="Version for alias">
                <SelectValue placeholder="Select version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    v{v.version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            type="button"
            size="sm"
            disabled={
              !effectiveAlias || !aliasVersionId || setAliasMutation.isPending
            }
            onClick={handleSetAlias}
          >
            {setAliasMutation.isPending ? "Saving…" : "Set alias"}
          </Button>
        </div>
      </section>

      {versions.length === 0 ? (
        <EmptyState
          title="No versions"
          description="Register a new version from your app via the SDK or API, then refresh this page."
          action={
            <Link
              href={backHref}
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              Back to list
            </Link>
          }
        />
      ) : (
        <>
          <DataTable
            rows={versions}
            columns={columns}
            getRowKey={(row) => row.id}
            selectedIndex={selectedIndex}
            onSelectedIndexChange={setSelectedIndex}
            onRowActivate={(_row, index) => setSelectedIndex(index)}
            aria-label="App config versions"
          />

          {selectedVersion ? (
            <section className="flex flex-col gap-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-sm font-medium text-foreground">
                  Version detail · v{selectedVersion.version}
                </h2>
                <span className="font-mono text-xs text-muted-foreground">
                  hash {selectedVersion.content_hash.slice(0, 12)}…
                </span>
              </div>
              {selectedVersion.description?.trim() ? (
                <p className="text-sm text-muted-foreground">
                  {selectedVersion.description.trim()}
                </p>
              ) : null}
              <div className="grid gap-3 md:grid-cols-3">
                <DetailBlock title="Prompt">
                  {formatConfigValue(selectedVersion.prompt)}
                </DetailBlock>
                <DetailBlock title="Model">
                  {formatConfigValue(selectedVersion.model)}
                </DetailBlock>
                <DetailBlock title="Retrieval">
                  {formatConfigValue(selectedVersion.retrieval)}
                </DetailBlock>
              </div>
            </section>
          ) : null}

          <details className="rounded-md border border-border px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-foreground">
              Compare versions
            </summary>
            <div className="mt-3 flex flex-col gap-2">
              <div className="flex flex-wrap gap-3">
                <VersionPicker
                  label="Version A"
                  versions={versions}
                  value={compareA}
                  onChange={setCompareA}
                />
                <VersionPicker
                  label="Version B"
                  versions={versions}
                  value={compareB}
                  onChange={setCompareB}
                />
              </div>
              {configA && configB ? (
                <div className="grid gap-3 md:grid-cols-2">
                  <ComparePane title={`v${configA.version}`} config={configA} />
                  <ComparePane title={`v${configB.version}`} config={configB} />
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Select two versions to compare side by side.
                </p>
              )}
            </div>
          </details>
        </>
      )}
    </div>
  );
}

function VersionPicker({
  label,
  versions,
  value,
  onChange,
}: {
  label: string;
  versions: AppConfig[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="w-[180px]">
      <label className="mb-1 block text-xs text-muted-foreground">{label}</label>
      <Select value={value} onValueChange={(v) => onChange(v ?? "")}>
        <SelectTrigger aria-label={label}>
          <SelectValue placeholder="Select" />
        </SelectTrigger>
        <SelectContent>
          {versions.map((v) => (
            <SelectItem key={v.id} value={v.id}>
              v{v.version}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function ComparePane({
  title,
  config,
}: {
  title: string;
  config: AppConfig;
}) {
  return (
    <div className="rounded-md border border-border bg-surface">
      <div className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
        {title}
      </div>
      <div className="max-h-[min(480px,50vh)] overflow-auto p-3 text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground">
        {configPlainSnapshot(config)}
      </div>
    </div>
  );
}

function AliasChip({
  alias,
  onDelete,
  deleting,
}: {
  alias: AppConfigAlias;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant="secondary" className="font-mono text-xs">
        {alias.name} → v{alias.app_config.version}
      </Badge>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="size-6"
        aria-label={`Remove alias ${alias.name}`}
        disabled={deleting}
        onClick={onDelete}
      >
        <Trash2 className="size-3" />
      </Button>
    </span>
  );
}
