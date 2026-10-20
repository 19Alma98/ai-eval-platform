# One image for API and UI: the static UI export is built here and served by
# FastAPI, exactly like `opengrade ui` serves the packaged wheel.

FROM node:22-alpine AS ui
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# Sub-path behind a reverse proxy, e.g. --build-arg NEXT_PUBLIC_BASE_PATH=/opengrade
ARG NEXT_PUBLIC_BASE_PATH=
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY sdk/pyproject.toml sdk/README.md sdk/hatch_build.py /sdk/
COPY sdk/src /sdk/src

COPY backend/pyproject.toml backend/README.md backend/hatch_build.py ./
COPY backend/src ./src
COPY --from=ui /frontend/out ./src/opengrade_server/_ui
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/docker-entrypoint.sh ./

RUN uv pip install --system --no-cache . \
    && python -c "from pathlib import Path; p = Path('docker-entrypoint.sh'); data = p.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n').lstrip(b'\xef\xbb\xbf'); p.write_bytes(data); p.chmod(0o755)"

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
