"use client";

import { useCallback, useMemo, useState } from "react";
import {
  resolveTimezone,
  timezoneOptions,
  writeStoredTimezone,
} from "./time-range";

/** Browser/localStorage timezone for chart labels (API stays UTC). */
export function useTimezone() {
  const [timeZone, setTimeZoneState] = useState(() => resolveTimezone());

  const setTimeZone = useCallback((next: string) => {
    const tz = next.trim() || resolveTimezone(null);
    writeStoredTimezone(tz);
    setTimeZoneState(tz);
  }, []);

  const options = useMemo(() => timezoneOptions(timeZone), [timeZone]);

  return { timeZone, setTimeZone, options };
}
