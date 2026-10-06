export const PROJECT_DEFAULT_SELECT = "project-default";

export function metricsSetIdForCreate(selected: string): string | null {
  if (!selected || selected === PROJECT_DEFAULT_SELECT) return null;
  return selected;
}

export function evaluatePackBody(opts: {
  overrideSetId: string | null;
  saveAsDefault: boolean;
}): { metrics_set_id?: string; save_as_default?: boolean } {
  if (!opts.overrideSetId) return {};
  return {
    metrics_set_id: opts.overrideSetId,
    save_as_default: opts.saveAsDefault,
  };
}
