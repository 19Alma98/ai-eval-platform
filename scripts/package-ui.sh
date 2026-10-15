#!/usr/bin/env bash
# Build the Next.js static export and sync it into opengrade_server/_ui.
# Delegates to the cross-platform Python script (works on Windows via python).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/package_ui.py"
