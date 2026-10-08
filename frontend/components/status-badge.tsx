import { cn } from "@/lib/cn";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-status-ok-bg text-status-ok",
  success: "bg-status-ok-bg text-status-ok",
  warn: "bg-status-warn-bg text-status-warn",
  warning: "bg-status-warn-bg text-status-warn",
  fail: "bg-status-fail-bg text-status-fail",
  error: "bg-status-fail-bg text-status-fail",
};

const STATUS_LABELS: Record<string, string> = {
  ok: "OK",
  success: "Success",
  warn: "Warning",
  warning: "Warning",
  fail: "Failed",
  failed: "Failed",
  error: "Error",
  pass: "Passed",
  passed: "Passed",
  complete: "Completed",
  completed: "Completed",
  pending: "Pending",
  skipped: "Skipped",
  regression: "Regression",
  improved: "Improved",
  unchanged: "Unchanged",
  unavailable: "Unavailable",
  config_mismatch: "Config mismatch",
  insufficient_n: "Insufficient n",
  unset: "Unset",
};

function capitalizeWord(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

/** Human-readable English label for known API status strings. */
export function formatStatusLabel(status: string): string {
  const key = status.trim().toLowerCase();
  if (key in STATUS_LABELS) return STATUS_LABELS[key]!;
  return capitalizeWord(status.trim());
}

export function statusTone(status: string): string {
  const s = status.toLowerCase();
  if (s in STATUS_STYLES) return s;
  if (s === "pass" || s === "passed" || s === "complete" || s === "completed") {
    return "ok";
  }
  if (s === "fail" || s === "failed") return "fail";
  if (s === "error") return "error";
  if (s === "skipped" || s === "insufficient_n") return "warn";
  return "unset";
}

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const key = statusTone(status);
  const style =
    STATUS_STYLES[key] ?? "bg-status-unset-bg text-status-unset";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
        style,
        className,
      )}
    >
      {formatStatusLabel(status)}
    </span>
  );
}
