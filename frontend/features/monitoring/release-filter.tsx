"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ReleaseFacets, ReleaseFilter } from "@/lib/api/types";

const ALL = "__all__";

/** `?env=` / `?version=` in the URL, shared by the Health and Traces views. */
export function useReleaseFilter(): [ReleaseFilter, (key: "env" | "version", value: string | null) => void] {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filter: ReleaseFilter = {
    environment: searchParams.get("env") || null,
    version: searchParams.get("version") || null,
  };
  const setFilter = useCallback(
    (key: "env" | "version", value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set(key, value);
      else params.delete(key);
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );
  return [filter, setFilter];
}

/** Environment and version pickers; hidden while the project reports neither. */
export function ReleaseFilterControls({
  facets,
  filter,
  onChange,
}: {
  facets: ReleaseFacets | undefined;
  filter: ReleaseFilter;
  onChange: (key: "env" | "version", value: string | null) => void;
}) {
  const environments = withSelected(facets?.environments ?? [], filter.environment);
  const versions = withSelected(facets?.versions ?? [], filter.version);
  if (environments.length === 0 && versions.length === 0) return null;
  return (
    <>
      {environments.length > 0 ? (
        <FacetSelect
          label="Environment"
          allLabel="All environments"
          values={environments}
          value={filter.environment ?? null}
          onChange={(v) => onChange("env", v)}
        />
      ) : null}
      {versions.length > 0 ? (
        <FacetSelect
          label="Version"
          allLabel="All versions"
          values={versions}
          value={filter.version ?? null}
          onChange={(v) => onChange("version", v)}
        />
      ) : null}
    </>
  );
}

function withSelected(values: { value: string; n_traces: number }[], selected?: string | null) {
  // Keep a filter from the URL selectable even when the range has no traces for it.
  if (!selected || values.some((v) => v.value === selected)) return values;
  return [{ value: selected, n_traces: 0 }, ...values];
}

function FacetSelect({
  label,
  allLabel,
  values,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  values: { value: string; n_traces: number }[];
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <Select value={value ?? ALL} onValueChange={(v) => onChange(v && v !== ALL ? v : null)}>
      <SelectTrigger aria-label={label} className="h-8 w-[170px] text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {values.map((v) => (
          <SelectItem key={v.value} value={v.value}>
            {v.value}
            <span className="ml-1 text-muted-foreground">({v.n_traces})</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
