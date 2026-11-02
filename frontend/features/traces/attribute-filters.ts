/**
 * Trace attribute filters (tags, metadata key:value, user, session), kept in the URL:
 * `?tag=beta&tag=eu&meta=tenant:acme&user=u1&session=chat-1`. Every filter must match.
 */

export type AttributeFilters = {
  tags: string[];
  metadata: string[]; // "key:value"
  user: string | null;
  session: string | null;
};

export type AttributeChip =
  | { kind: "tag"; value: string }
  | { kind: "meta"; value: string }
  | { kind: "user"; value: string }
  | { kind: "session"; value: string };

export const EMPTY_ATTRIBUTE_FILTERS: AttributeFilters = {
  tags: [],
  metadata: [],
  user: null,
  session: null,
};

function unique(values: string[]): string[] {
  return [...new Set(values.map((v) => v.trim()).filter(Boolean))];
}

export function readAttributeFilters(params: URLSearchParams): AttributeFilters {
  return {
    tags: unique(params.getAll("tag")),
    metadata: unique(params.getAll("meta")).filter((m) => parseMetadataPair(m) !== null),
    user: params.get("user")?.trim() || null,
    session: params.get("session")?.trim() || null,
  };
}

export function hasAttributeFilters(f: AttributeFilters): boolean {
  return f.tags.length > 0 || f.metadata.length > 0 || f.user !== null || f.session !== null;
}

/** "key:value" split on the first colon; null when either side is empty. */
export function parseMetadataPair(text: string): { key: string; value: string } | null {
  const i = text.indexOf(":");
  if (i <= 0) return null;
  const key = text.slice(0, i).trim();
  const value = text.slice(i + 1).trim();
  return key && value ? { key, value } : null;
}

/**
 * What the user typed in the filter box: `tag:beta`, `user:u1`, `session:chat-1`,
 * `key:value` (metadata), or a bare word (a tag).
 */
export function parseFilterInput(text: string): AttributeChip | null {
  const raw = text.trim();
  if (!raw) return null;
  const pair = parseMetadataPair(raw);
  if (pair === null) return raw.includes(":") ? null : { kind: "tag", value: raw };
  switch (pair.key.toLowerCase()) {
    case "tag":
      return { kind: "tag", value: pair.value };
    case "user":
      return { kind: "user", value: pair.value };
    case "session":
      return { kind: "session", value: pair.value };
    default:
      return { kind: "meta", value: `${pair.key}:${pair.value}` };
  }
}

export function chipsOf(f: AttributeFilters): AttributeChip[] {
  return [
    ...(f.user ? [{ kind: "user" as const, value: f.user }] : []),
    ...(f.session ? [{ kind: "session" as const, value: f.session }] : []),
    ...f.tags.map((value) => ({ kind: "tag" as const, value })),
    ...f.metadata.map((value) => ({ kind: "meta" as const, value })),
  ];
}

export function addChip(f: AttributeFilters, chip: AttributeChip): AttributeFilters {
  switch (chip.kind) {
    case "tag":
      return { ...f, tags: unique([...f.tags, chip.value]) };
    case "meta":
      return { ...f, metadata: unique([...f.metadata, chip.value]) };
    case "user":
      return { ...f, user: chip.value };
    case "session":
      return { ...f, session: chip.value };
  }
}

export function removeChip(f: AttributeFilters, chip: AttributeChip): AttributeFilters {
  switch (chip.kind) {
    case "tag":
      return { ...f, tags: f.tags.filter((t) => t !== chip.value) };
    case "meta":
      return { ...f, metadata: f.metadata.filter((m) => m !== chip.value) };
    case "user":
      return { ...f, user: null };
    case "session":
      return { ...f, session: null };
  }
}

/** Replace the attribute params of `params` with `f` (other params are kept). */
export function writeAttributeFilters(
  params: URLSearchParams,
  f: AttributeFilters,
): URLSearchParams {
  const next = new URLSearchParams(params.toString());
  for (const key of ["tag", "meta", "user", "session"]) next.delete(key);
  for (const tag of f.tags) next.append("tag", tag);
  for (const meta of f.metadata) next.append("meta", meta);
  if (f.user) next.set("user", f.user);
  if (f.session) next.set("session", f.session);
  return next;
}

/** Trace list URL (all time) filtered by one attribute, e.g. from a trace detail chip. */
export function tracesFilteredHref(chip: AttributeChip): string {
  const params = writeAttributeFilters(
    new URLSearchParams({ range: "all" }),
    addChip(EMPTY_ATTRIBUTE_FILTERS, chip),
  );
  return `/traces?${params.toString()}`;
}

export function chipLabel(chip: AttributeChip): string {
  switch (chip.kind) {
    case "tag":
      return `#${chip.value}`;
    case "meta":
      return chip.value;
    case "user":
      return `user: ${chip.value}`;
    case "session":
      return `session: ${chip.value}`;
  }
}

/** Stable string for query keys. */
export function attributeFiltersKey(f: AttributeFilters): string {
  return writeAttributeFilters(new URLSearchParams(), f).toString();
}

const MAX_HEADER_METADATA = 8;

/**
 * Filterable trace metadata (scalar values; ``_``-prefixed keys are internal), as the
 * server indexes it: booleans as "true"/"false".
 */
export function metadataEntries(
  metadata: Record<string, unknown> | null | undefined,
  max = MAX_HEADER_METADATA,
): [string, string][] {
  const out: [string, string][] = [];
  for (const [key, value] of Object.entries(metadata ?? {})) {
    if (!key || key.startsWith("_")) continue;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      const text = String(value);
      if (text) out.push([key, text]);
    }
    if (out.length >= max) break;
  }
  return out;
}
