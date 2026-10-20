import assert from "node:assert/strict";
import { test } from "node:test";
import type { Dataset } from "@/lib/api/types";
import { groupDatasetVersions } from "./dataset-versions";

function ds(name: string, version: number, created_at: string): Dataset {
  return {
    id: `${name}-${version}`,
    project_id: "p",
    name,
    version,
    description: null,
    task_type: "rag_qa",
    created_at,
  };
}

test("groups versions under the newest one, newest test set first", () => {
  const rows = groupDatasetVersions([
    ds("faq", 1, "2026-10-01T00:00:00Z"),
    ds("billing", 1, "2026-10-03T00:00:00Z"),
    ds("faq", 2, "2026-10-05T00:00:00Z"),
  ]);
  assert.deepEqual(
    rows.map((r) => [r.id, r.latest, r.versionCount]),
    [
      ["faq-2", true, 2],
      ["faq-1", false, 2],
      ["billing-1", true, 1],
    ],
  );
});
