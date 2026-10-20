import type React from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  action,
  className,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  /** Extra control next to "Try again" (e.g. a link back to the list). */
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-md border border-border bg-surface px-6 py-12 text-center",
        className,
      )}
    >
      <AlertCircle className="mb-3 size-8 text-status-fail" aria-hidden />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {message ? (
        <p className="mt-2 max-w-md text-sm text-muted-foreground">{message}</p>
      ) : null}
      {onRetry || action ? (
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          {onRetry ? (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Try again
            </Button>
          ) : null}
          {action}
        </div>
      ) : null}
    </div>
  );
}
