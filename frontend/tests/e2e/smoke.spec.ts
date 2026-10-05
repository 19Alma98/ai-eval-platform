import { test, expect } from "@playwright/test";

const API = process.env.API_ORIGIN ?? "http://localhost:8000";

test("trace list and release page render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E", slug: `e2e-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  await page.goto(`/traces?project=${id}`);
  await expect(page.getByRole("heading", { name: "Traces" })).toBeVisible();

  const main = page.locator("main");
  const emptyTraces = main.getByText("No traces yet");
  const tracesTable = main.getByRole("region", { name: "Traces" });
  await expect(emptyTraces.or(tracesTable)).toBeVisible();

  await page.goto(`/release?project=${id}`);
  await expect(page.getByRole("heading", { name: "Release" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to Experiments" })).toBeVisible();
  await expect(page.getByLabel("Policy (YAML)")).toHaveCount(0);
});

test("quality loop strip and glossaries render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E UX", slug: `e2e-ux-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  await page.goto(`/overview?project=${id}`);
  await expect(page.getByRole("navigation", { name: "Quality loop" })).toBeVisible();
  await expect(page.getByText(/quality loop/i).first()).toBeVisible();

  await page.goto(`/traces?project=${id}&status=error`);
  await expect(page.getByRole("button", { name: "Error" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.goto(`/experiments?project=${id}`);
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await expect(page.getByText(/evaluation run on a dataset/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /new experiment/i })).toBeVisible();
});
