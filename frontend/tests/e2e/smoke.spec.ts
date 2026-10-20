// page.goto uses Playwright baseURL (PLAYWRIGHT_BASE_URL); point it at the FE instance under test.
import { test, expect } from "@playwright/test";

const API = process.env.API_ORIGIN ?? "http://localhost:8000";

test("overview, live traffic and quality gate render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E", slug: `e2e-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  await page.goto(`/overview?project=${id}&range=24h`);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByRole("button", { name: /time range/i })).toBeVisible();
  const keyMetrics = page.getByRole("region", { name: "Key metrics" });
  await expect(
    keyMetrics.getByRole("heading", { name: "Live", exact: true }),
  ).toBeVisible();
  await expect(
    keyMetrics.getByRole("heading", { name: "Offline", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Traces" })).toBeVisible();

  await page.goto(`/live-runs?project=${id}`);
  await expect(page.getByRole("heading", { name: "Live traffic" })).toBeVisible();

  await page.goto(`/release?project=${id}`);
  await expect(page.getByRole("heading", { name: "Quality gate" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to Experiments" })).toBeVisible();
  await expect(page.getByLabel("Rules (YAML)")).toHaveCount(0);
});

test("navigation, getting started and glossaries render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E UX", slug: `e2e-ux-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  await page.goto(`/overview?project=${id}`);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Getting started" })).toBeVisible();

  await page.goto(`/experiments?project=${id}`);
  await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
  await expect(page.getByText(/runs one version of your app on a test set/i)).toBeVisible();
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
  await expect(page.getByRole("heading", { name: /new experiment/i })).toBeVisible();
  await page.getByLabel("Test set").click();
  await page.getByRole("option").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
});

test("traces, production and experiment comparison render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E Monitor", slug: `e2e-mon-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  const traceId = "ab".repeat(16);
  const nanos = (msAgo: number) => `${Date.now() - msAgo}000000`;
  const otlp = await request.post(`${API}/v1/traces`, {
    headers: { "X-Project-Id": id },
    data: {
      resourceSpans: [
        {
          scopeSpans: [
            {
              spans: [
                {
                  traceId,
                  spanId: "11".repeat(8),
                  name: "answer",
                  startTimeUnixNano: nanos(2000),
                  endTimeUnixNano: nanos(1000),
                  status: { code: "STATUS_CODE_OK" },
                  attributes: [
                    { key: "openinference.span.kind", value: { stringValue: "RETRIEVER" } },
                    {
                      key: "retrieval.documents",
                      value: {
                        stringValue: JSON.stringify([
                          { id: "doc-1", text: "Remote work is allowed.", score: 0.9 },
                        ]),
                      },
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
  });
  expect(otlp.ok()).toBeTruthy();

  await page.goto(`/traces?project=${id}`);
  await expect(page.getByRole("heading", { name: "Traces" })).toBeVisible();
  await page.getByRole("region", { name: "Traces" }).getByText("answer").click();
  await expect(page).toHaveURL(new RegExp(`/traces/${traceId}`));
  await expect(page.getByText("Retrieved chunks")).toBeVisible();
  await expect(page.getByText("doc-1")).toBeVisible();

  await page.goto(`/monitoring?project=${id}&range=1h`);
  await expect(page.getByRole("heading", { name: "Production" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Production KPIs" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Annotation queue" })).toBeVisible();

  await page.goto(`/experiments/compare?project=${id}`);
  await expect(page.getByRole("heading", { name: "Compare experiments" })).toBeVisible();
});
