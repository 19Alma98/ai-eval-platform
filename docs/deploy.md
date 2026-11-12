# Deploy

Two ways to run the OpenGrade server (API + UI + OTLP ingest on one port):

| | When | Storage |
|---|---|---|
| `opengrade ui` | trying it out, local development, a single developer | SQLite file (`./opengrade.db`) |
| Docker Compose | a team, CI baselines that must persist, production traffic | PostgreSQL |

Both serve the same UI and API. The SDK only needs the URL (`OPENGRADE_TRACKING_URI`,
default `http://localhost:8000`) and, when the server requires one, an API key.

## Local: `opengrade ui`

```bash
uvx --from 'opengrade-ai[ui]' opengrade ui      # nothing installed in your project
# or, inside a project:
uv add 'opengrade-ai[ui]' && uv run opengrade ui
```

It creates `./opengrade.db` in the current directory and reads a `.env` from there. At startup
it prints the judge model it picked up and warns about missing judge credentials or an open
server.

The same command can use PostgreSQL instead of SQLite:

```bash
uv run opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

## Team server: Docker Compose

[`docker-compose.yml`](../docker-compose.yml) at the repository root runs two containers:
`postgres` (PostgreSQL 16) and `api`, the published image
`ghcr.io/19alma98/ai-eval-platform/opengrade` (API and packaged UI, runs as non-root
`uid`/`gid` `10001`).

```bash
git clone https://github.com/19Alma98/ai-eval-platform && cd ai-eval-platform
cp backend/.env.example backend/.env      # judges, API key, limits: every setting with its default
docker compose pull                       # published image; OPENGRADE_IMAGE_TAG=0.2.1 pins a version
docker compose up -d                      # http://localhost:8000
```

```bash
curl http://localhost:8000/health   # process is up
curl http://localhost:8000/ready    # database reachable (503 otherwise)
```

Compose sets `DATABASE_URL` to the `postgres` container and publishes both services on
`127.0.0.1` only (API on `8000`, PostgreSQL on `5434`). The container applies database migrations before
starting the API. `docker compose up --build` builds the image from the checkout instead of pulling it.

!!! warning "Supported topology: one API replica"
    Background work (judge scoring, alerts, retention) runs inside the API process. Run a single
    API container; several replicas would pick up each other's work on restart.

## Configuration

Settings are environment variables: in `backend/.env` with Compose, in `.env` (or the
environment) with `opengrade ui`. The full list with defaults and comments is
[`backend/.env.example`](../backend/.env.example). The ones you are most likely to set:

| Variable | Purpose |
|---|---|
| `LLM_MODEL` / `LLM_API_KEY` / `LLM_API_BASE` | Judge model, via [LiteLLM](https://docs.litellm.ai/docs/providers) (`openai/gpt-4o-mini`, `ollama/gemma4:e2b`, …) |
| `OPENGRADE_API_KEY` | Bootstrap admin key. Unset = open server (localhost or a trusted network only) |
| `DATABASE_URL` | Async SQLAlchemy URL (set by Compose; SQLite by default with `opengrade ui`) |
| `CONTENT_CAPTURE_ENABLED` | Store span text, prompts and document text (`true`). `false` redacts it at ingest: retrieval metrics still work, text judges are skipped |
| `PUBLIC_BASE_URL` | External URL of the UI, for links in alert notifications |
| `ALERT_WEBHOOK_URL` | Default webhook (Slack or any JSON endpoint) for alert rules without their own |
| `RETENTION_DAYS` | Delete production data older than this; projects can override it |
| `FORWARDED_ALLOW_IPS` | Proxies trusted for `X-Forwarded-*` (default `*`) |
| `OTLP_*` | Ingest body size, sampling and backpressure limits |

### Judge credentials

`LLM_API_KEY` works for every provider. With Compose, the provider's own variables in
`backend/.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, AWS, Azure or Vertex credentials) work
too, because Compose passes the file to the container environment. For a local Ollama from
inside Compose use `LLM_API_BASE=http://host.docker.internal:11434`.

Without a judge model, tracing and the deterministic metrics work; LLM judges are reported as
skipped with `judge not configured`, and a quality-gate threshold on one of them fails as
`unavailable`. Which model is good enough: [minimum judge model](03-evaluation-engine.md#minimum-judge-model).

## Before exposing it beyond localhost

1. Set `OPENGRADE_API_KEY` (a long random value, e.g. `openssl rand -hex 32`) and create
   per-client keys with the `read`, `ingest` or `admin` scope in **Settings → API keys** or with
   `opengrade keys create`.
2. Terminate TLS at a reverse proxy and set `FORWARDED_ALLOW_IPS` to the proxy address.
3. Point the SDK at it: `OPENGRADE_TRACKING_URI=https://opengrade.example.com` and
   `OPENGRADE_API_KEY=<ingest or admin key>`.

Under load, OTLP ingest answers `429` / `503` with `Retry-After`; the SDK retries. Details,
trust model and content capture: [Security and API keys](10-security-privacy.md).

## CI

A CI job needs the baseline alias to survive between runs, so it talks to the team server
(`api_base_url` in `opengrade.yaml`, plus an API key) or to a durable database
(`--backend-store-uri`). Setup and a GitHub Actions example: [CLI and CI](08-cli-ci.md).
