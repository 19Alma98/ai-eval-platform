import { PRESETS, type Preset } from "@/lib/time-range";

export const OVERVIEW_DEFAULT_PRESET: Preset = "24h";

export function parseOverviewRangeParam(
  raw: string | null | undefined,
): Preset {
  if (raw && (PRESETS as string[]).includes(raw)) return raw as Preset;
  return OVERVIEW_DEFAULT_PRESET;
}
