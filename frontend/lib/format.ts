const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatRelativeTime(date: Date, now = new Date()): string {
  const diffMs = date.getTime() - now.getTime();
  const absSec = Math.abs(Math.round(diffMs / 1000));
  if (absSec < 60) return rtf.format(Math.round(diffMs / 1000), "second");
  const absMin = Math.abs(Math.round(diffMs / 60_000));
  if (absMin < 60) return rtf.format(Math.round(diffMs / 60_000), "minute");
  const absHr = Math.abs(Math.round(diffMs / 3_600_000));
  if (absHr < 24) return rtf.format(Math.round(diffMs / 3_600_000), "hour");
  return rtf.format(Math.round(diffMs / 86_400_000), "day");
}

export function formatTs(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

export function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s % 1 === 0 ? s : s.toFixed(2)}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem.toFixed(0)}s`;
}

export function truncateId(id: string, len = 8): string {
  if (id.length <= len) return id;
  return `${id.slice(0, len)}…`;
}

/** Prefer a denormalized or looked-up name; never use a raw UUID as the label. */
export function resolveLabel(
  id: string | null | undefined,
  nameById?: Map<string, string> | null,
  fallback = "Unknown",
): string {
  if (id) {
    const lookedUp = nameById?.get(id)?.trim();
    if (lookedUp) return lookedUp;
  }
  return fallback;
}
