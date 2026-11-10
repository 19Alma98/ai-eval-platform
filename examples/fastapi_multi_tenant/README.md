# FastAPI multi-tenant (multiple `Opengrade` instances)

One API worker serves two OpenGrade projects. At startup each tenant gets an `Opengrade` handle with
its own `project_slug`; each HTTP request calls `with og.activate():` so tracing and
`og.client` use the right project headers.

## Prerequisites

Platform API on `:8000` with projects **acme** and **contoso** (slugs), or let `set_project` create
them on first traced request. See [getting started](../../docs/getting-started.md).

## Run

From the monorepo (uses the SDK under `sdk/`):

```bash
cd sdk && uv sync
cd ../examples/fastapi_multi_tenant
uv run --project ../../sdk --with fastapi --with uvicorn uvicorn main:app --reload
# curl -H 'X-Tenant: acme' 'http://127.0.0.1:8000/ask?q=hello'
```

After **opengrade-ai 0.2.0** is on PyPI you can instead `uv run --with 'opengrade-ai' --with fastapi --with uvicorn ...`.

Expected UI: traces under **acme** or **contoso** depending on `X-Tenant`.

## Notes

- `OPENGRADE_TRACKING_URI` overrides the default `http://localhost:8000`.
- Tenant slugs default to `acme` / `contoso`; override with `TENANT_ACME_SLUG` / `TENANT_CONTOSO_SLUG`.
- For background threads, wrap work with `contextvars.copy_context().run(...)` or open `activate()`
  inside the thread so `ContextVar` routing matches the request.
