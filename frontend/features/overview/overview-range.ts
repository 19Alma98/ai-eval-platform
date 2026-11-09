import { isPreset, type Preset } from "@/lib/time-range";

export const OVERVIEW_DEFAULT_PRESET: Preset = "24h";

export function parseOverviewRangeParam(
  raw: string | null | undefined,
): Preset {
  if (isPreset(raw)) return raw;
  return OVERVIEW_DEFAULT_PRESET;
}
