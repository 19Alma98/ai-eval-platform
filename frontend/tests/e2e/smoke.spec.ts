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
  // Empty project: Getting started replaces the "Before release" panel.
  const live = page.getByRole("region", { name: "In production" });
  await expect(live.getByRole("heading", { name: "No live traffic" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Before release" })).toHaveCount(0);
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Production" }),
  ).toBeVisible();

  await page.goto(`/live-runs?project=${id}`);
  await expect(page.getByRole("heading", { name: "Production" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Production views" }).getByRole("link", { name: "Live answers" }),
  ).toHaveAttribute("aria-current", "page");

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
  await expect(
    page.getByRole("navigation", { name: "Production views" }).getByRole("link", { name: "Traces" }),
  ).toHaveAttribute("aria-current", "page");
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

test("LLM, tool and retrieval spans can be inspected", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E Spans", slug: `e2e-spans-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  const traceId = "cd".repeat(16);
  const rootId = "21".repeat(8);
  const nanos = (msAgo: number) => `${Date.now() - msAgo}000000`;
  const str = (key: string, value: string) => ({ key, value: { stringValue: value } });
  const int = (key: string, value: number) => ({ key, value: { intValue: String(value) } });
  const span = (
    spanId: string,
    name: string,
    kind: string,
    attributes: object[],
    parentSpanId?: string,
  ) => ({
    traceId,
    spanId,
    parentSpanId,
    name,
    startTimeUnixNano: nanos(4000),
    endTimeUnixNano: nanos(1000),
    status: { code: "STATUS_CODE_OK" },
    attributes: [str("openinference.span.kind", kind), ...attributes],
  });
  const otlp = await request.post(`${API}/v1/traces`, {
    headers: { "X-Project-Id": id },
    data: {
      resourceSpans: [
        {
          scopeSpans: [
            {
              spans: [
                span(rootId, "agent", "CHAIN", [
                  str("input.value", "Weather in Rome?"),
                  str("output.value", "Sunny, 24C."),
                ]),
                span("22".repeat(8), "search_docs", "RETRIEVER", [
                  str("input.value", "rome weather"),
                  str(
                    "retrieval.documents",
                    JSON.stringify([{ id: "doc-weather", text: "Rome forecast", score: 0.8 }]),
                  ),
                ], rootId),
                span("23".repeat(8), "get_weather", "TOOL", [
                  str("tool.name", "get_weather"),
                  str("input.value", '{"city":"Rome"}'),
                  str("output.value", "sunny-24c"),
                ], rootId),
                span("24".repeat(8), "chat_completion", "LLM", [
                  str("llm.model_name", "demo-model-1"),
                  str("input.value", "Summarise the forecast"),
                  str("output.value", "Sunny, 24C."),
                  int("llm.token_count.total", 42),
                ], rootId),
              ],
            },
          ],
        },
      ],
    },
  });
  expect(otlp.ok()).toBeTruthy();

  await page.goto(`/traces/${traceId}?project=${id}`);
  await page.getByRole("tab", { name: "Timeline" }).click();

  const open = async (name: string) => {
    await page.getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  };

  const attributes = page.getByRole("tabpanel", { name: "Attributes" });
  const io = page.getByRole("tabpanel", { name: "Input / Output" });

  await open("chat_completion");
  // Header facts: kind and total tokens.
  await expect(page.getByRole("definition").filter({ hasText: /^LLM$/ })).toBeVisible();
  await expect(page.getByRole("definition").filter({ hasText: /^42$/ })).toBeVisible();
  await expect(attributes.getByText("demo-model-1")).toBeVisible();
  await page.getByRole("tab", { name: "Input / Output" }).click();
  await expect(io.getByText("Summarise the forecast")).toBeVisible();

  await open("get_weather");
  await expect(page.getByRole("definition").filter({ hasText: /^TOOL$/ })).toBeVisible();
  await page.getByRole("tab", { name: "Input / Output" }).click();
  await expect(io.getByText("sunny-24c")).toBeVisible();

  await open("search_docs");
  await expect(page.getByRole("definition").filter({ hasText: /^RETRIEVER$/ })).toBeVisible();
  await page.getByRole("tab", { name: "Attributes" }).click();
  await expect(attributes.getByText(/doc-weather/)).toBeVisible();
});
