import { cn } from "@/lib/cn";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-status-ok-bg text-status-ok",
  success: "bg-status-ok-bg text-status-ok",
  warn: "bg-status-warn-bg text-status-warn",
  warning: "bg-status-warn-bg text-status-warn",
  fail: "bg-status-fail-bg text-status-fail",
  error: "bg-status-fail-bg text-status-fail",
};

function normalizeStatus(status: string): string {
  const s = status.toLowerCase();
  if (s in STATUS_STYLES) return s;
  if (s === "passed" || s === "complete") return "ok";
  if (s === "failed") return "fail";
  return "unset";
}

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const key = normalizeStatus(status);
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
