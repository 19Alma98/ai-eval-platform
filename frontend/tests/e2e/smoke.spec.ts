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
  await expect(page.getByText(/No traces yet|trace/i)).toBeVisible();

  await page.goto(`/release?project=${id}`);
  await expect(page.getByRole("heading", { name: "Release" })).toBeVisible();
  await expect(page.getByText(/policy/i)).toBeVisible();
});
