import { withProjectQuery } from "./project-href";

/**
 * Stable deep links for every object the UI shows. The SDK prints the same paths
 * (see `aiobs._links`), so keep both in sync.
 */
export function traceHref(projectId: string | null, traceId: string): string {
  return withProjectQuery(`/traces/${encodeURIComponent(traceId)}`, projectId);
}

export function experimentHref(
  projectId: string | null,
  experimentId: string,
): string {
  return withProjectQuery(`/experiments/${encodeURIComponent(experimentId)}`, projectId);
}

export function experimentItemHref(
  projectId: string | null,
  experimentId: string,
  datasetItemId: string,
): string {
  return withProjectQuery(
    `/experiments/${encodeURIComponent(experimentId)}?item=${encodeURIComponent(datasetItemId)}`,
    projectId,
  );
}

export function experimentsCompareHref(
  projectId: string | null,
  experimentIds: string[],
): string {
  const ids = experimentIds.map(encodeURIComponent).join(",");
  return withProjectQuery(`/experiments/compare${ids ? `?ids=${ids}` : ""}`, projectId);
}

export function liveRunHref(projectId: string | null, interactionId: string): string {
  return withProjectQuery(`/live-runs/${encodeURIComponent(interactionId)}`, projectId);
}
