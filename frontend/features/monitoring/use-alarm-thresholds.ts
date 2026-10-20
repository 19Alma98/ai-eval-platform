"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";
import { parseAlarmThresholds } from "./alarms";

const ALARMS_KEY = "opengrade.monitoring.alarms";

// Fallback when localStorage is unavailable: keep values for this visit.
const memory = new Map<string, string>();
const listeners = new Set<() => void>();

function readRaw(storageKey: string): string | null {
  const kept = memory.get(storageKey);
  if (kept !== undefined) return kept;
  try {
    return localStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

function writeRaw(storageKey: string, raw: string) {
  try {
    localStorage.setItem(storageKey, raw);
  } catch {
    memory.set(storageKey, raw);
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/**
 * Per-project alarm thresholds. Values are always read for the current
 * project's key, so switching projects can never show (or re-save) the
 * previous project's thresholds.
 */
export function useAlarmThresholds(projectId: string) {
  const storageKey = `${ALARMS_KEY}.${projectId}`;
  const raw = useSyncExternalStore(
    subscribe,
    () => readRaw(storageKey),
    () => null,
  );
  const thresholds = useMemo(() => parseAlarmThresholds(raw), [raw]);
  const update = useCallback(
    (key: string, value: number | null) => {
      const next = { ...parseAlarmThresholds(readRaw(storageKey)) };
      if (value == null) delete next[key];
      else next[key] = value;
      writeRaw(storageKey, JSON.stringify(next));
    },
    [storageKey],
  );
  return [thresholds, update] as const;
}
