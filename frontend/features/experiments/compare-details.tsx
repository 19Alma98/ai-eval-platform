"use client";

import type { CompareOptionalColumn } from "./compare-url-state";

type CompareDetailsProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  visibleCols: Set<CompareOptionalColumn>;
  onVisibleColsChange: (cols: Set<CompareOptionalColumn>) => void;
};

/** Optional columns of the quality table (params and run metrics live in CompareChangesPanel). */
export function CompareDetails({
  open,
  onOpenChange,
  visibleCols,
  onVisibleColsChange,
}: CompareDetailsProps) {
  function toggleCol(col: CompareOptionalColumn, checked: boolean) {
    const next = new Set(visibleCols);
    if (checked) next.add(col);
    else next.delete(col);
    onVisibleColsChange(next);
  }

  return (
    <details
      className="rounded-lg border border-border bg-surface px-4 py-3"
      open={open}
      onToggle={(event) => {
        onOpenChange((event.currentTarget as HTMLDetailsElement).open);
      }}
    >
      <summary className="cursor-pointer text-sm font-medium text-foreground">
        Table columns
        <span className="ml-2 font-normal text-muted-foreground">
          confidence interval, average score
        </span>
      </summary>

      <fieldset className="mt-3 flex flex-wrap gap-4">
        <legend className="sr-only">Quality table columns</legend>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            className="size-3.5 accent-foreground"
            checked={visibleCols.has("ci")}
            onChange={(e) => toggleCol("ci", e.target.checked)}
          />
          Confidence interval
        </label>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            className="size-3.5 accent-foreground"
            checked={visibleCols.has("score")}
            onChange={(e) => toggleCol("score", e.target.checked)}
          />
          Average score
        </label>
      </fieldset>
    </details>
  );
}
