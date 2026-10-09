#!/bin/sh
set -e

echo "Waiting for database and applying migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn aiobs_server.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"