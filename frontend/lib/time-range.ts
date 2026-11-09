export type Preset = "15m" | "1h" | "6h" | "24h" | "7d";

export type TimeRangeKind = Preset | "custom";

export type TimeWindow = {
  start: Date;
  end: Date;
  kind: TimeRangeKind;
};

const MS: Record<Preset, number> = {
  "15m": 15 * 60_000,
  "1h": 60 * 60_000,
  "6h": 6 * 60 * 60_000,
  "24h": 24 * 60 * 60_000,
  "7d": 7 * 24 * 60 * 60_000,
};

export function rangeFromPreset(preset: Preset, now = new Date()): TimeWindow & { preset: Preset } {
  return {
    start: new Date(now.getTime() - MS[preset]),
    end: now,
    kind: preset,
    preset,
  };
}

/** Same duration as `[start, end)`, shifted immediately before `start`. */
export function previousPeriod(start: Date, end: Date): { start: Date; end: Date } {
  const durationMs = Math.max(0, end.getTime() - start.getTime());
  return {
    start: new Date(start.getTime() - durationMs),
    end: new Date(start.getTime()),
  };
}

export const PRESET_LABELS: Record<Preset, string> = {
  "15m": "15m",
  "1h": "1h",
  "6h": "6h",
  "24h": "24h",
  "7d": "7d",
};

export const PRESETS = Object.keys(MS) as Preset[];

export function isPreset(value: string | null | undefined): value is Preset {
  return Boolean(value && (PRESETS as string[]).includes(value));
}

/** Curated IANA zones plus the browser default when missing. */
export const COMMON_TIMEZONES = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Rome",
  "Europe/Madrid",
  "Europe/Amsterdam",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Asia/Kolkata",
  "Australia/Sydney",
] as const;

const TZ_STORAGE_KEY = "opengrade.timezone";

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function readStoredTimezone(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(TZ_STORAGE_KEY)?.trim();
    return raw || null;
  } catch {
    return null;
  }
}

export function writeStoredTimezone(timeZone: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TZ_STORAGE_KEY, timeZone);
  } catch {
    // ignore quota / private mode
  }
}

export function resolveTimezone(stored: string | null = readStoredTimezone()): string {
  return stored?.trim() || browserTimezone();
}

export function timezoneOptions(preferred?: string | null): string[] {
  const set = new Set<string>(COMMON_TIMEZONES);
  const browser = browserTimezone();
  set.add(browser);
  if (preferred?.trim()) set.add(preferred.trim());
  return [...set].sort((a, b) => a.localeCompare(b));
}

function parseIsoDate(raw: string | null | undefined): Date | null {
  if (!raw?.trim()) return null;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * Read monitoring/overview window from URL.
 * Preset: `?range=24h`. Custom: `?range=custom&since=<iso>&until=<iso>`.
 */
export function parseTimeRangeParams(
  params: { get(name: string): string | null },
  opts: { defaultPreset: Preset; anchor?: Date },
): TimeWindow {
  const { defaultPreset, anchor = new Date() } = opts;
  const range = params.get("range");
  if (range === "custom") {
    const start = parseIsoDate(params.get("since"));
    const end = parseIsoDate(params.get("until"));
    if (start && end && start.getTime() < end.getTime()) {
      return { start, end, kind: "custom" };
    }
    return rangeFromPreset(defaultPreset, anchor);
  }
  if (isPreset(range)) return rangeFromPreset(range, anchor);
  return rangeFromPreset(defaultPreset, anchor);
}

/** Apply a window to URLSearchParams (mutates). Clears since/until for presets. */
export function writeTimeRangeParams(params: URLSearchParams, window: TimeWindow): void {
  if (window.kind === "custom") {
    params.set("range", "custom");
    params.set("since", window.start.toISOString());
    params.set("until", window.end.toISOString());
    return;
  }
  params.set("range", window.kind);
  params.delete("since");
  params.delete("until");
}

/** `<input type="datetime-local">` value in a given IANA zone. */
export function toDatetimeLocalValue(date: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

/**
 * Parse a datetime-local wall time in `timeZone` to a UTC Date.
 * Uses the offset at that civil time (handles DST via a resolve pass).
 */
export function fromDatetimeLocalValue(value: string, timeZone: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value.trim());
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  // First guess: treat the wall time as UTC, then correct by the zone offset.
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  const offsetMs = zoneOffsetMs(new Date(asUtc), timeZone);
  const corrected = new Date(asUtc - offsetMs);
  // Re-check offset at the corrected instant (DST boundary).
  const offset2 = zoneOffsetMs(corrected, timeZone);
  if (offset2 !== offsetMs) return new Date(asUtc - offset2);
  return corrected;
}

function zoneOffsetMs(date: Date, timeZone: string): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "shortOffset",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const name = dtf.formatToParts(date).find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  // "GMT", "GMT+2", "GMT-05:30", "UTC"
  const match = /([+-])(\d{1,2})(?::?(\d{2}))?/.exec(name);
  if (!match) return 0;
  const sign = match[1] === "-" ? -1 : 1;
  const hours = Number(match[2]);
  const minutes = Number(match[3] ?? "0");
  return sign * (hours * 60 + minutes) * 60_000;
}
