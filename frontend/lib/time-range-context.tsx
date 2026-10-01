"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { rangeFromPreset, type Preset, PRESETS } from "./time-range";

type TimeRangeContextValue = {
  start: Date;
  end: Date;
  preset: string;
  setPreset: (p: string) => void;
};

const TimeRangeContext = createContext<TimeRangeContextValue | null>(null);

export function TimeRangeProvider({ children }: { children: ReactNode }) {
  const [preset, setPresetState] = useState<Preset>("1h");
  const [endAnchor, setEndAnchor] = useState(() => new Date());

  const range = useMemo(
    () => rangeFromPreset(preset, endAnchor),
    [preset, endAnchor],
  );

  const setPreset = useCallback((p: string) => {
    if ((PRESETS as string[]).includes(p)) {
      setPresetState(p as Preset);
      setEndAnchor(new Date());
    }
  }, []);

  const value = useMemo(
    () => ({
      start: range.start,
      end: range.end,
      preset,
      setPreset,
    }),
    [range.start, range.end, preset, setPreset],
  );

  return (
    <TimeRangeContext.Provider value={value}>
      {children}
    </TimeRangeContext.Provider>
  );
}

export function useTimeRange(): TimeRangeContextValue {
  const ctx = useContext(TimeRangeContext);
  if (!ctx) {
    throw new Error("useTimeRange must be used within TimeRangeProvider");
  }
  return ctx;
}
