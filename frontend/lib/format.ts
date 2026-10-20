const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** Parse API timestamps; naive ISO (no offset) is treated as UTC. */
export function parseTimestamp(value: string | Date): Date {
  if (value instanceof Date) return value;
  const trimmed = value.trim();
  if (
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(trimmed)
  ) {
    return new Date(`${trimmed}Z`);
  }
  return new Date(trimmed);
}

export function formatRelativeTime(date: Date, now = new Date()): string {
  const diffMs = date.getTime() - now.getTime();
  const past = diffMs <= 0;
  const absMs = Math.abs(diffMs);
  const absSec = Math.floor(absMs / 1000);
  if (absSec < 60) return rtf.format(past ? -absSec : absSec, "second");
  const absMin = Math.floor(absMs / 60_000);
  if (absMin < 60) return rtf.format(past ? -absMin : absMin, "minute");
  const absHr = Math.floor(absMs / 3_600_000);
  if (absHr < 24) return rtf.format(past ? -absHr : absHr, "hour");
  const absDay = Math.floor(absMs / 86_400_000);
  return rtf.format(past ? -absDay : absDay, "day");
}

export function formatTs(iso: string | Date): string {
  const d = typeof iso === "string" ? parseTimestamp(iso) : iso;
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

/** Scores are 0–1; two decimals is enough precision to read at a glance. */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

/** 0.583 → "58%"; keeps one decimal only when it changes the reading. */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const pct = value * 100;
  const rounded = Math.round(pct);
  return Math.abs(pct - rounded) < 0.05 ? `${rounded}%` : `${pct.toFixed(1)}%`;
}

/** Signed delta in percentage points for 0–1 scores: -0.1667 → "−17 pts". */
export function formatDeltaPoints(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const pts = Math.round(value * 100);
  if (pts === 0) return "±0";
  return pts > 0 ? `+${pts} pts` : `−${Math.abs(pts)} pts`;
}

const HOUR_MS = 3_600_000;

/**
 * Chart time-axis tick: time only for short ranges, weekday + time up to two days,
 * date + time beyond, so 24h / 7d axes don't repeat ambiguous "14:00" labels.
 */
export function formatBucketTick(
  iso: string,
  spanMs: number,
  locale?: string,
  timeZone?: string,
): string {
  const d = parseTimestamp(iso);
  const time = { hour: "2-digit", minute: "2-digit" } as const;
  if (spanMs <= 6 * HOUR_MS) return d.toLocaleTimeString(locale, { ...time, timeZone });
  if (spanMs <= 48 * HOUR_MS) {
    return d.toLocaleString(locale, { weekday: "short", ...time, timeZone });
  }
  return d.toLocaleString(locale, { month: "short", day: "numeric", ...time, timeZone });
}
