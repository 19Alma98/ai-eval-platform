#!/bin/sh
set -e

echo "Waiting for database and applying migrations..."
python -m opengrade_server.migrate

echo "Starting API..."
exec uvicorn opengrade_server.main:app \
  --host "${APP_HOST:-0.0.0.0}" \
  --port "${APP_PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --timeout-graceful-shutdown "${SHUTDOWN_GRACE_SECONDS:-30}"
