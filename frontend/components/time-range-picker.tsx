"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PRESET_LABELS, PRESETS } from "@/lib/time-range";
import { useTimeRange } from "@/lib/time-range-context";

export function TimeRangePicker({
  preset: presetProp,
  onPresetChange,
}: {
  preset?: string;
  onPresetChange?: (p: string) => void;
} = {}) {
  const ctx = useTimeRange();
  const preset = presetProp ?? ctx.preset;
  const setPreset = onPresetChange ?? ctx.setPreset;

  return (
    <Select
      value={preset}
      onValueChange={(v) => {
        if (v) setPreset(v);
      }}
    >
      <SelectTrigger className="h-8 w-[88px] text-xs" aria-label="Time range">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {PRESETS.map((p) => (
          <SelectItem key={p} value={p} className="text-xs">
            {PRESET_LABELS[p]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
