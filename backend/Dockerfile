FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY sdk/pyproject.toml sdk/README.md sdk/hatch_build.py /sdk/
COPY sdk/src /sdk/src

COPY backend/pyproject.toml backend/README.md backend/hatch_build.py ./
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/docker-entrypoint.sh ./

RUN uv pip install --system --no-cache . \
    && python -c "from pathlib import Path; p = Path('docker-entrypoint.sh'); data = p.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n').lstrip(b'\xef\xbb\xbf'); p.write_bytes(data); p.chmod(0o755)"

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
