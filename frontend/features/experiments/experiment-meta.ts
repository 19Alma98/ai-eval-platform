import type { Experiment } from "@/lib/api/types";

/** User-declared model label from experiment.model_config.model */
export function experimentModel(experiment: Experiment): string | null {
  const raw = experiment.model_config?.model;
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function experimentVersion(experiment: Experiment): string | null {
  const trimmed = experiment.version?.trim();
  return trimmed ? trimmed : null;
}
