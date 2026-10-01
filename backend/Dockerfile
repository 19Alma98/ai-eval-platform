FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

RUN uv pip install --system --no-cache . \
    && python -c "from pathlib import Path; p = Path('docker-entrypoint.sh'); data = p.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n').lstrip(b'\xef\xbb\xbf'); p.write_bytes(data); p.chmod(0o755)"

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
