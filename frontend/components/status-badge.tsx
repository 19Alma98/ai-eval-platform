import { cn } from "@/lib/cn";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-status-ok-bg text-status-ok",
  success: "bg-status-ok-bg text-status-ok",
  warn: "bg-status-warn-bg text-status-warn",
  warning: "bg-status-warn-bg text-status-warn",
  fail: "bg-status-fail-bg text-status-fail",
  error: "bg-status-fail-bg text-status-fail",
};

export function statusTone(status: string): string {
  const s = status.toLowerCase();
  if (s in STATUS_STYLES) return s;
  if (s === "pass" || s === "passed" || s === "complete" || s === "completed") {
    return "ok";
  }
  if (s === "fail" || s === "failed") return "fail";
  if (s === "error") return "error";
  if (s === "skipped") return "warn";
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
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium capitalize",
        style,
        className,
      )}
    >
      {status}
    </span>
  );
}
