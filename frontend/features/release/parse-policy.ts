import { load } from "js-yaml";

function assertPolicyMapping(doc: unknown): Record<string, unknown> {
  if (doc === null || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("Policy must be a YAML mapping");
  }
  const record = doc as Record<string, unknown>;
  if (
    Object.keys(record).length === 1 &&
    record.null === null &&
    Object.prototype.hasOwnProperty.call(record, "null")
  ) {
    throw new Error("Invalid YAML");
  }
  return record;
}

export function parsePolicyYaml(source: string): Record<string, unknown> {
  try {
    return assertPolicyMapping(load(source));
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error("Invalid YAML");
  }
}
