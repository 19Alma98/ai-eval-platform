import { cn } from "@/lib/cn";

export function LoadingBlock({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md border border-border bg-surface-2 p-8",
        className,
      )}
      role="status"
      aria-label="Loading"
    >
      <div className="mx-auto h-4 w-1/3 rounded bg-border" />
      <div className="mx-auto mt-3 h-3 w-1/2 rounded bg-border/70" />
    </div>
  );
}
