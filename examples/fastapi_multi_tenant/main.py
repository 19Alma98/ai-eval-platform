"""FastAPI: one Opengrade instance per tenant, activate per request."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated

import opengrade
from fastapi import FastAPI, Header, HTTPException
from opengrade import Opengrade, Settings

TRACKING_URI = os.getenv("OPENGRADE_TRACKING_URI", "http://localhost:8000")
TENANT_SLUGS = {
    "acme": os.getenv("TENANT_ACME_SLUG", "acme"),
    "contoso": os.getenv("TENANT_CONTOSO_SLUG", "contoso"),
}

TENANTS: dict[str, Opengrade] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for tenant_id, slug in TENANT_SLUGS.items():
        og = Opengrade(
            settings=Settings(
                tracking_uri=TRACKING_URI,
                project_slug=slug,
                service_name=f"fastapi-{tenant_id}",
            )
        )
        og.init_tracing(instrument=False)
        TENANTS[tenant_id] = og
    yield
    for og in TENANTS.values():
        og.close()


app = FastAPI(title="OpenGrade multi-tenant demo", lifespan=lifespan)


@opengrade.trace(name="answer")
def answer(question: str) -> str:
    proj = opengrade.get_project()
    slug = proj.slug if proj is not None else "unknown"
    return f"[{slug}] {question}"


@app.get("/ask")
async def ask(
    q: str,
    x_tenant: Annotated[str, Header(alias="X-Tenant")],
) -> dict[str, str]:
    og = TENANTS.get(x_tenant.lower())
    if og is None:
        raise HTTPException(status_code=404, detail=f"unknown tenant {x_tenant!r}")
    with og.activate():
        if opengrade.get_project() is None:
            og.set_project(TENANT_SLUGS[x_tenant.lower()])
        text = answer(q)
        opengrade.flush()
        return {"tenant": x_tenant, "answer": text}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "tenants": ",".join(sorted(TENANTS))}
