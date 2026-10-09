#!/usr/bin/env bash
# Build the Next.js static export and sync it into aiobs_server/_ui for wheel packaging.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
DEST="$ROOT/backend/src/aiobs_server/_ui"

cd "$FRONTEND"
npm ci
npm run build:package

rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$FRONTEND/out/." "$DEST/"

echo "Packaged UI → $DEST"
test -f "$DEST/index.html"
