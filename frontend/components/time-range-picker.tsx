"use client";

import { useState } from "react";
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

const CUSTOM = "custom";

export function TimeRangePicker({
  window,
  onWindowChange,
  timeZone,
  onTimeZoneChange,
  timeZoneOptions,
  showCustom = false,
  showTimezone = false,
}: {
  window: TimeWindow;
  onWindowChange: (window: TimeWindow) => void;
  timeZone?: string;
  onTimeZoneChange?: (tz: string) => void;
  timeZoneOptions?: string[];
  showCustom?: boolean;
  showTimezone?: boolean;
}) {
  const kind = window.kind;

  const [draftStart, setDraftStart] = useState("");
  const [draftEnd, setDraftEnd] = useState("");
  const [draftSourceKey, setDraftSourceKey] = useState<string | null>(null);

  const sourceKey =
    showCustom && timeZone
      ? `${window.start.getTime()}-${window.end.getTime()}-${timeZone}`
      : null;
  if (sourceKey !== draftSourceKey) {
    setDraftSourceKey(sourceKey);
    if (sourceKey && timeZone) {
      setDraftStart(toDatetimeLocalValue(window.start, timeZone));
      setDraftEnd(toDatetimeLocalValue(window.end, timeZone));
    }
  }

  function applyCustom() {
    if (!timeZone) return;
    const start = fromDatetimeLocalValue(draftStart, timeZone);
    const end = fromDatetimeLocalValue(draftEnd, timeZone);
    if (!start || !end || start.getTime() >= end.getTime()) return;
    onWindowChange({ start, end, kind: "custom" });
  }

  function onSelectChange(v: string | null) {
    if (!v) return;
    if (v === CUSTOM) {
      onWindowChange({ start: window.start, end: window.end, kind: "custom" });
      return;
    }
    if (isPreset(v)) {
      onWindowChange({
        start: window.start,
        end: window.end,
        kind: v,
      });
    }
  }

  const selectValue = kind === "custom" ? CUSTOM : kind;

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
