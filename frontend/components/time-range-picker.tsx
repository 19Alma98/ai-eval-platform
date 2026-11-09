"use client";

import { useEffect, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  PRESET_LABELS,
  PRESETS,
  fromDatetimeLocalValue,
  isPreset,
  toDatetimeLocalValue,
  type TimeWindow,
} from "@/lib/time-range";
import { useTimeRange } from "@/lib/time-range-context";

const CUSTOM = "custom";

export function TimeRangePicker({
  preset: presetProp,
  onPresetChange,
  window: windowProp,
  onWindowChange,
  timeZone,
  onTimeZoneChange,
  timeZoneOptions,
  showCustom = false,
  showTimezone = false,
}: {
  /** Legacy preset-only API (overview/context). */
  preset?: string;
  onPresetChange?: (p: string) => void;
  /** Full window API (monitoring with custom ranges). */
  window?: TimeWindow;
  onWindowChange?: (window: TimeWindow) => void;
  timeZone?: string;
  onTimeZoneChange?: (tz: string) => void;
  timeZoneOptions?: string[];
  showCustom?: boolean;
  showTimezone?: boolean;
} = {}) {
  const ctx = useTimeRange();
  const kind = windowProp?.kind ?? presetProp ?? ctx.preset;
  const setPreset = onPresetChange ?? ctx.setPreset;

  const [draftStart, setDraftStart] = useState("");
  const [draftEnd, setDraftEnd] = useState("");

  useEffect(() => {
    if (!showCustom || !windowProp || !timeZone) return;
    setDraftStart(toDatetimeLocalValue(windowProp.start, timeZone));
    setDraftEnd(toDatetimeLocalValue(windowProp.end, timeZone));
  }, [showCustom, windowProp, timeZone]);

  function applyCustom() {
    if (!onWindowChange || !timeZone) return;
    const start = fromDatetimeLocalValue(draftStart, timeZone);
    const end = fromDatetimeLocalValue(draftEnd, timeZone);
    if (!start || !end || start.getTime() >= end.getTime()) return;
    onWindowChange({ start, end, kind: "custom" });
  }

  function onSelectChange(v: string | null) {
    if (!v) return;
    if (v === CUSTOM) {
      if (onWindowChange && windowProp) {
        onWindowChange({ start: windowProp.start, end: windowProp.end, kind: "custom" });
      }
      return;
    }
    if (isPreset(v)) {
      if (onWindowChange) {
        // Parent recomputes from preset + fresh anchor.
        onWindowChange({
          start: windowProp?.start ?? new Date(),
          end: windowProp?.end ?? new Date(),
          kind: v,
        });
      }
      setPreset(v);
    }
  }

  const selectValue = kind === "custom" || kind === CUSTOM ? CUSTOM : kind;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select aria-label="Time range" value={selectValue} onValueChange={onSelectChange}>
        <SelectTrigger className="h-8 w-[88px] text-xs" aria-label="Time range">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PRESETS.map((p) => (
            <SelectItem key={p} value={p} className="text-xs">
              {PRESET_LABELS[p]}
            </SelectItem>
          ))}
          {showCustom ? (
            <SelectItem value={CUSTOM} className="text-xs">
              Custom
            </SelectItem>
          ) : null}
        </SelectContent>
      </Select>

      {showCustom && kind === "custom" ? (
        <>
          <Input
            type="datetime-local"
            value={draftStart}
            onChange={(e) => setDraftStart(e.target.value)}
            className="h-8 w-[11.5rem] text-xs"
            aria-label="Range start"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            type="datetime-local"
            value={draftEnd}
            onChange={(e) => setDraftEnd(e.target.value)}
            className="h-8 w-[11.5rem] text-xs"
            aria-label="Range end"
          />
          <Button type="button" size="sm" variant="outline" className="h-8 text-xs" onClick={applyCustom}>
            Apply
          </Button>
        </>
      ) : null}

      {showTimezone && timeZone && onTimeZoneChange && timeZoneOptions ? (
        <Select
          aria-label="Timezone"
          value={timeZone}
          onValueChange={(v) => {
            if (v) onTimeZoneChange(v);
          }}
        >
          <SelectTrigger className="h-8 w-[10.5rem] text-xs" aria-label="Timezone">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {timeZoneOptions.map((tz) => (
              <SelectItem key={tz} value={tz} className="text-xs">
                {tz}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
