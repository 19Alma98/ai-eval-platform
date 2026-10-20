"use client";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

export type PromoteDocPreview = {
  id: string;
  title?: string;
  text?: string;
};

export function mergeGoldDocIds(
  selectedIds: string[],
  extraCommaSeparated: string,
): string[] {
  return Array.from(
    new Set([
      ...selectedIds,
      ...extraCommaSeparated
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    ]),
  );
}

export function docsFromLiveInteraction(
  documents: Record<string, unknown>[],
): PromoteDocPreview[] {
  return documents.map((d) => ({
    id: String(d.id ?? ""),
    title: typeof d.title === "string" ? d.title : undefined,
    text: typeof d.text === "string" ? d.text : undefined,
  })).filter((d) => d.id);
}

/** Document pickers for promote-to-dataset (checkboxes + manual IDs). */
export function PromoteExpectedDocFields({
  documents,
  selectedIds,
  onSelectedIdsChange,
  extraDocIds,
  onExtraDocIdsChange,
  compact = false,
  idPrefix = "promote",
}: {
  documents: PromoteDocPreview[];
  selectedIds: string[];
  onSelectedIdsChange: (ids: string[]) => void;
  extraDocIds: string;
  onExtraDocIdsChange: (value: string) => void;
  compact?: boolean;
  idPrefix?: string;
}) {
  const extraId = `${idPrefix}-extra`;
  return (
    <div className={compact ? "flex flex-col gap-1.5" : "flex flex-col gap-4"}>
      {documents.length > 0 ? (
        <fieldset className="flex flex-col gap-1.5 text-sm">
          <legend className={compact ? "mb-0.5 text-xs font-medium" : "mb-1.5 font-medium"}>
            Which documents contain the answer?
          </legend>
          {documents.map((d) => (
            <label key={d.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={selectedIds.includes(d.id)}
                onChange={(e) =>
                  onSelectedIdsChange(
                    e.target.checked
                      ? [...selectedIds, d.id]
                      : selectedIds.filter((x) => x !== d.id),
                  )
                }
              />
              <span className="text-foreground">{d.title ?? d.id}</span>
              {d.title ? (
                <Badge variant="outline" className="font-normal">
                  {d.id}
                </Badge>
              ) : null}
            </label>
          ))}
        </fieldset>
      ) : null}
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={extraId}
          className={compact ? "text-xs font-medium" : "text-sm font-medium"}
        >
          {documents.length > 0
            ? "Other documents that should have been found"
            : "Expected document IDs"}{" "}
          {documents.length > 0 ? (
            <span className="font-normal text-muted-foreground">(optional)</span>
          ) : (
            <span className="font-normal text-muted-foreground">
              (required for RAG test sets)
            </span>
          )}
        </label>
        <Input
          id={extraId}
          value={extraDocIds}
          onChange={(e) => onExtraDocIdsChange(e.target.value)}
          placeholder="Document IDs, comma-separated"
          className={compact ? "h-8 bg-background text-sm" : undefined}
        />
      </div>
    </div>
  );
}
