// page.goto uses Playwright baseURL (PLAYWRIGHT_BASE_URL); point it at the FE instance under test.
import { test, expect } from "@playwright/test";

const API = process.env.API_ORIGIN ?? "http://localhost:8000";

test("overview live runs and release page render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E", slug: `e2e-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  await page.goto(`/overview?project=${id}&range=24h`);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByLabel("Time range")).toBeVisible();
  const keyMetrics = page.getByRole("region", { name: "Key metrics" });
  await expect(
    keyMetrics.getByRole("heading", { name: "Live", exact: true }),
  ).toBeVisible();
  await expect(
    keyMetrics.getByRole("heading", { name: "Offline", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Traces" })).toHaveCount(0);

  await page.goto(`/live-runs?project=${id}`);
  await expect(page.getByRole("heading", { name: "Live runs" })).toBeVisible();

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

  await page.goto(`/experiments?project=${id}`);
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await expect(page.getByText(/evaluation run on a dataset/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /new experiment/i })).toBeVisible();
});

test("create experiment dialog select works", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E Dialog", slug: `e2e-dlg-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  const ds = await request.post(`${API}/api/v1/projects/${id}/datasets`, {
    data: { name: "DS", task_type: "rag_qa", version: 1 },
  });
  expect(ds.ok()).toBeTruthy();

  await page.goto(`/experiments?project=${id}`);
  await page.getByRole("button", { name: /new experiment/i }).click();
  await expect(page.getByRole("heading", { name: /create experiment/i })).toBeVisible();
  await page.getByLabel("Dataset").click();
  await page.getByRole("option").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
});
