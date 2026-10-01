export type Preset = "15m" | "1h" | "6h" | "24h" | "7d";

const MS: Record<Preset, number> = {
  "15m": 15 * 60_000,
  "1h": 60 * 60_000,
  "6h": 6 * 60 * 60_000,
  "24h": 24 * 60 * 60_000,
  "7d": 7 * 24 * 60 * 60_000,
};

export function rangeFromPreset(preset: Preset, now = new Date()) {
  return { start: new Date(now.getTime() - MS[preset]), end: now, preset };
}

export const PRESET_LABELS: Record<Preset, string> = {
  "15m": "15m",
  "1h": "1h",
  "6h": "6h",
  "24h": "24h",
  "7d": "7d",
};

export const PRESETS = Object.keys(MS) as Preset[];
