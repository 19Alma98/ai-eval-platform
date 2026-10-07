/** Render registry config blobs as plain text (not JSON). */
export function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : "—";
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    return value
      .map((item, index) => {
        const line = formatConfigValue(item);
        return typeof item === "object" && item !== null
          ? `${index + 1}.\n${indentBlock(line)}`
          : `${index + 1}. ${line}`;
      })
      .join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "—";

    // Common shape: { system: "…" } or { model_id: "…" } → show the string alone.
    if (entries.length === 1 && typeof entries[0][1] === "string") {
      return formatConfigValue(entries[0][1]);
    }

    return entries
      .map(([key, nested]) => {
        const formatted = formatConfigValue(nested);
        if (
          typeof nested === "string" &&
          (nested.includes("\n") || nested.length > 72)
        ) {
          return `${key}\n${formatted}`;
        }
        if (nested !== null && typeof nested === "object") {
          return `${key}\n${indentBlock(formatted)}`;
        }
        return `${key}: ${formatted}`;
      })
      .join("\n\n");
  }
  return String(value);
}

function indentBlock(text: string, prefix = "  "): string {
  return text
    .split("\n")
    .map((line) => `${prefix}${line}`)
    .join("\n");
}
