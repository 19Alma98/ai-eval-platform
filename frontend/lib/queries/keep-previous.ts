import { keepPreviousData, type QueryKey } from "@tanstack/react-query";

/**
 * `placeholderData` that keeps the previous result on screen while a new key
 * loads (filter, search or time window change), but only when the previous
 * query belonged to the same project (query key position 1).
 */
export function keepPreviousInProject(projectId: string) {
  return <T>(prev: T | undefined, prevQuery?: { queryKey: QueryKey }) =>
    prevQuery?.queryKey[1] === projectId ? keepPreviousData(prev) : undefined;
}
