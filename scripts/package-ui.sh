#!/usr/bin/env bash
# Build the Next.js static export and sync it into opengrade_server/_ui.
# This is the only UI build: `opengrade ui`, the wheel and the Docker image all serve it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
DEST="$ROOT/backend/src/opengrade_server/_ui"

cd "$FRONTEND"
npm ci
npm run build

rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$FRONTEND/out/." "$DEST/"

echo "Packaged UI → $DEST"
test -f "$DEST/index.html"
