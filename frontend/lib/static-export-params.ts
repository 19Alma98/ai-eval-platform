/** Placeholder params so `output: "export"` emits HTML shells for dynamic routes. */

export const STATIC_EXPORT_PLACEHOLDER = "_";

export function placeholderParams(
  key: string,
): Array<Record<string, string>> {
  return [{ [key]: STATIC_EXPORT_PLACEHOLDER }];
}
