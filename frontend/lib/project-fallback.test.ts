import assert from "node:assert/strict";
import { test } from "node:test";
import { projectFallback } from "./project-fallback";

const projects = [
  { id: "a", name: "Alpha" },
  { id: "b", name: "Beta" },
];

test("keeps a project that exists, or while the list is loading", () => {
  assert.deepEqual(projectFallback("b", projects), { action: "keep" });
  assert.deepEqual(projectFallback("gone", undefined), { action: "keep" });
  assert.deepEqual(projectFallback(null, projects), { action: "keep" });
});

test("switches a deleted project to the first one", () => {
  assert.deepEqual(projectFallback("gone", projects), { action: "switch", to: projects[0] });
});

test("clears the selection when no project is left", () => {
  assert.deepEqual(projectFallback("gone", []), { action: "clear" });
});
