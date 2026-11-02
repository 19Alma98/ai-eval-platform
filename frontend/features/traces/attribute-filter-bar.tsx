"use client";

import { X } from "lucide-react";
import { useId, useState } from "react";
import { Input } from "@/components/ui/input";
import type { TraceFacets } from "@/lib/api/types";
import {
  type AttributeChip,
  type AttributeFilters,
  addChip,
  chipLabel,
  chipsOf,
  parseFilterInput,
  removeChip,
} from "./attribute-filters";

const MAX_SUGGESTIONS = 30;

function suggestions(facets: TraceFacets | undefined): string[] {
  if (!facets) return [];
  return [
    ...facets.tags.map((f) => `tag:${f.value}`),
    ...facets.metadata_keys.map((f) => `${f.value}:`),
    ...facets.users.map((f) => `user:${f.value}`),
    ...facets.sessions.map((f) => `session:${f.value}`),
  ].slice(0, MAX_SUGGESTIONS * 4);
}

/** Filter box (`tag:beta`, `tenant:acme`, `user:u1`, `session:…`) plus removable chips. */
export function AttributeFilterBar({
  filters,
  facets,
  onChange,
}: {
  filters: AttributeFilters;
  facets: TraceFacets | undefined;
  onChange: (next: AttributeFilters) => void;
}) {
  const listId = useId();
  const [text, setText] = useState("");
  const [invalid, setInvalid] = useState(false);
  const chips = chipsOf(filters);

  const submit = () => {
    if (!text.trim()) return;
    const chip = parseFilterInput(text);
    if (chip === null) {
      setInvalid(true);
      return;
    }
    onChange(addChip(filters, chip));
    setText("");
    setInvalid(false);
  };

  const remove = (chip: AttributeChip) => onChange(removeChip(filters, chip));

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <div className="flex flex-col">
        <Input
          type="text"
          list={listId}
          placeholder="Filter: tag:beta, tenant:acme, user:…"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setInvalid(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          onBlur={() => {
            if (!text.trim()) setInvalid(false);
          }}
          aria-label="Filter traces by tag, metadata, user or session"
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? `${listId}-hint` : undefined}
          className="h-8 w-64 max-w-full"
        />
        <datalist id={listId}>
          {suggestions(facets).map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        {invalid ? (
          <span id={`${listId}-hint`} className="mt-1 text-xs text-status-fail">
            Use key:value (e.g. tenant:acme), tag:name, user:id or session:id
          </span>
        ) : null}
      </div>
      {chips.length > 0 ? (
        <ul className="flex flex-wrap items-center gap-1" aria-label="Active trace filters">
          {chips.map((chip) => (
            <li key={`${chip.kind}:${chip.value}`}>
              <span className="inline-flex max-w-[240px] items-center gap-1 rounded-md border border-border bg-surface-2 py-0.5 pr-0.5 pl-2 text-xs">
                <span className="truncate" title={chipLabel(chip)}>
                  {chipLabel(chip)}
                </span>
                <button
                  type="button"
                  onClick={() => remove(chip)}
                  className="rounded p-0.5 text-muted-foreground hover:bg-row-selected hover:text-foreground"
                  aria-label={`Remove filter ${chipLabel(chip)}`}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            </li>
          ))}
          {chips.length > 1 ? (
            <li>
              <button
                type="button"
                onClick={() =>
                  onChange({ tags: [], metadata: [], user: null, session: null })
                }
                className="px-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
              >
                Clear
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

/** Tag chips for a table cell; a click filters the list by that tag. */
export function TagChips({
  tags,
  onSelect,
  max = 3,
}: {
  tags: string[];
  onSelect?: (tag: string) => void;
  max?: number;
}) {
  if (tags.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {tags.slice(0, max).map((tag) =>
        onSelect ? (
          <button
            key={tag}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(tag);
            }}
            className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-foreground hover:bg-row-selected"
            title={`Show traces tagged ${tag}`}
          >
            #{tag}
          </button>
        ) : (
          <span key={tag} className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">
            #{tag}
          </span>
        ),
      )}
      {tags.length > max ? (
        <span className="text-xs text-muted-foreground">+{tags.length - max}</span>
      ) : null}
    </span>
  );
}
