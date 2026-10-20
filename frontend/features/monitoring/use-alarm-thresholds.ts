"use client";

import { useCallback, useEffect, useState } from "react";
import { parseAlarmThresholds, type AlarmThresholds } from "./alarms";

const ALARMS_KEY = "opengrade.monitoring.alarms";

export function useAlarmThresholds(projectId: string) {
  const storageKey = `${ALARMS_KEY}.${projectId}`;
  const [thresholds, setThresholds] = useState<AlarmThresholds>({});
  useEffect(() => {
    try {
      setThresholds(parseAlarmThresholds(localStorage.getItem(storageKey)));
    } catch {
      setThresholds({});
    }
  }, [storageKey]);
  const update = useCallback(
    (key: string, value: number | null) => {
      setThresholds((prev) => {
        const next = { ...prev };
        if (value == null) delete next[key];
        else next[key] = value;
        try {
          localStorage.setItem(storageKey, JSON.stringify(next));
        } catch {
          /* storage unavailable: keep for this visit */
        }
        return next;
      });
    },
    [storageKey],
  );
  return [thresholds, update] as const;
}
