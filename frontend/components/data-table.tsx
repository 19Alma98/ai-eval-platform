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
};

export function DataTable<T>({
  rows,
  columns,
  getRowKey,
  selectedIndex,
  onSelectedIndexChange,
  onRowActivate,
  className,
  "aria-label": ariaLabel = "Data table",
}: {
  rows: T[];
  columns: DataTableColumn<T>[];
  getRowKey: (row: T, index: number) => string;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
  onRowActivate: (row: T, index: number) => void;
  className?: string;
  "aria-label"?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (rows.length === 0) return;
    if (selectedIndex >= rows.length) {
      onSelectedIndexChange(rows.length - 1);
    }
  }, [rows.length, selectedIndex, onSelectedIndexChange]);

  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (rows.length === 0) return;
    const target = e.target as HTMLElement;
    if (
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT" ||
      target.isContentEditable
    ) {
      return;
    }

    if (e.key === "j") {
      e.preventDefault();
      onSelectedIndexChange(Math.min(selectedIndex + 1, rows.length - 1));
    } else if (e.key === "k") {
      e.preventDefault();
      onSelectedIndexChange(Math.max(selectedIndex - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[selectedIndex];
      if (row) onRowActivate(row, selectedIndex);
    }
  }

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      role="region"
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      className={cn(
        "overflow-auto rounded-md border border-border outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_0_hsl(var(--border))]">
          <tr>
            {columns.map((col) => (
              <th
                key={col.id}
                scope="col"
                className={cn(
                  "whitespace-nowrap px-2 py-1.5 text-left text-xs font-medium text-muted-foreground",
                  col.headerClassName,
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={getRowKey(row, index)}
              aria-selected={index === selectedIndex}
              className={cn(
                "cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-row-hover",
                index === selectedIndex && "bg-row-selected",
              )}
              onClick={() => {
                onSelectedIndexChange(index);
                onRowActivate(row, index);
              }}
            >
              {columns.map((col) => (
                <td
                  key={col.id}
                  className={cn(
                    "max-w-[240px] truncate px-2 py-1.5 align-middle",
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
