"use client";

import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { cn } from "@/lib/cn";

export type DataTableColumn<T> = {
  id: string;
  header: string;
  cell: (row: T, index: number) => ReactNode;
  className?: string;
  headerClassName?: string;
  /** Let long text wrap (use with line-clamp) instead of truncating to one line. */
  wrap?: boolean;
};

export function DataTable<T>({
  rows,
  columns,
  getRowKey,
  selectedIndex,
  onSelectedIndexChange,
  onRowActivate,
  className,
  selectionMode = "focus",
  "aria-label": ariaLabel = "Data table",
}: {
  rows: T[];
  columns: DataTableColumn<T>[];
  getRowKey: (row: T, index: number) => string;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
  onRowActivate: (row: T, index: number) => void;
  className?: string;
  /**
   * "persistent": the selected row stays highlighted (master–detail views).
   * "focus": highlight only the keyboard-focused row (navigation lists).
   */
  selectionMode?: "persistent" | "focus";
  "aria-label"?: string;
}) {
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  useEffect(() => {
    if (rows.length === 0) return;
    if (selectedIndex >= rows.length) {
      onSelectedIndexChange(rows.length - 1);
    }
  }, [rows.length, selectedIndex, onSelectedIndexChange]);

  // Roving tabindex: one row is in the tab order; arrows / j / k move it.
  const focusIndex = Math.min(Math.max(selectedIndex, 0), Math.max(rows.length - 1, 0));

  function moveTo(index: number) {
    onSelectedIndexChange(index);
    rowRefs.current[index]?.focus();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTableSectionElement>) {
    if (rows.length === 0) return;
    const target = e.target as HTMLElement;
    // Keys typed into a control inside a cell (or on a link/button) are theirs.
    if (target.tagName !== "TR") return;

    if (e.key === "j" || e.key === "ArrowDown") {
      e.preventDefault();
      moveTo(Math.min(focusIndex + 1, rows.length - 1));
    } else if (e.key === "k" || e.key === "ArrowUp") {
      e.preventDefault();
      moveTo(Math.max(focusIndex - 1, 0));
    } else if (e.key === "Home") {
      e.preventDefault();
      moveTo(0);
    } else if (e.key === "End") {
      e.preventDefault();
      moveTo(rows.length - 1);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const row = rows[focusIndex];
      if (row) onRowActivate(row, focusIndex);
    }
  }

  return (
    <div
      role="region"
      aria-label={ariaLabel}
      className={cn(
        "overflow-auto rounded-lg border border-border bg-surface",
        className,
      )}
    >
      <table
        role="grid"
        aria-label={ariaLabel}
        className="w-full border-collapse text-sm"
      >
        <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_0_hsl(var(--border))]">
          <tr>
            {columns.map((col) => (
              <th
                key={col.id}
                scope="col"
                className={cn(
                  "whitespace-nowrap px-3 py-2 text-left text-xs font-medium text-muted-foreground",
                  col.headerClassName,
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody onKeyDown={handleKeyDown}>
          {rows.map((row, index) => (
            <tr
              key={getRowKey(row, index)}
              ref={(el) => {
                rowRefs.current[index] = el;
              }}
              tabIndex={index === focusIndex ? 0 : -1}
              aria-selected={index === selectedIndex}
              className={cn(
                "cursor-pointer border-b border-border outline-none transition-colors last:border-b-0 hover:bg-row-hover focus-visible:bg-row-selected focus-visible:shadow-[inset_2px_0_0_0_hsl(var(--ring))]",
                index === selectedIndex &&
                  selectionMode === "persistent" &&
                  "bg-row-selected",
              )}
              onClick={() => {
                onSelectedIndexChange(index);
                onRowActivate(row, index);
              }}
            >
              {columns.map((col) => (
                <td
                  key={col.id}
                  role="gridcell"
                  className={cn(
                    col.wrap
                      ? "px-3 py-2 align-middle whitespace-normal break-words"
                      : "max-w-[240px] truncate px-3 py-2 align-middle",
                    col.className,
                  )}
                >
                  {col.cell(row, index)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
