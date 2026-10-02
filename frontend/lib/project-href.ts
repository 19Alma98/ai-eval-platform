/** Append or merge ?project= without dropping other query params already on href. */
export function withProjectQuery(
  href: string,
  projectId: string | null | undefined,
): string {
  if (!projectId) return href;
  const [path, qs = ""] = href.split("?");
  const params = new URLSearchParams(qs);
  params.set("project", projectId);
  const q = params.toString();
  return q ? `${path}?${q}` : path;
}
