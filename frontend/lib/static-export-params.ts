/** Placeholder params so `output: "export"` emits HTML shells for dynamic routes. */

export const STATIC_EXPORT_PLACEHOLDER = "_";

export function placeholderParams(
  key: string,
): Array<Record<string, string>> {
  return [{ [key]: STATIC_EXPORT_PLACEHOLDER }];
}

/**
 * When the packaged static UI serves the `_` shell for a real dynamic URL,
 * Next's `useParams()` keeps the bake-time placeholder. Prefer the pathname segment.
 */
export function resolveStaticExportParam(
  paramValue: string | string[] | undefined,
  pathname: string,
  segmentPattern: RegExp,
): string {
  const fromParams =
    typeof paramValue === "string"
      ? paramValue
      : Array.isArray(paramValue)
        ? (paramValue[0] ?? "")
        : "";
  if (fromParams && fromParams !== STATIC_EXPORT_PLACEHOLDER) {
    return fromParams;
  }
  const fromPath = pathname.match(segmentPattern)?.[1] ?? "";
  if (!fromPath || fromPath === STATIC_EXPORT_PLACEHOLDER) {
    return "";
  }
  return fromPath;
}
