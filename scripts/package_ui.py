#!/usr/bin/env python3
"""Build the Next.js static export and sync it into opengrade_server/_ui.

Cross-platform entry point (Windows/macOS/Linux). Requires Node.js/npm in PATH.
The bash wrapper ``scripts/package-ui.sh`` delegates here for CI compatibility.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    frontend = root / "frontend"
    dest = root / "backend" / "src" / "opengrade_server" / "_ui"
    out_dir = frontend / "out"

    npm = shutil.which("npm")
    if npm is None:
        print(
            "npm not found in PATH. Install Node.js >= 22, then re-run "
            "`python scripts/package_ui.py`.",
            file=sys.stderr,
        )
        return 1

    if not frontend.is_dir():
        print(f"frontend directory not found: {frontend}", file=sys.stderr)
        return 1

    for args in ([npm, "ci"], [npm, "run", "build"]):
        print(f"+ {' '.join(args)} (cwd={frontend})")
        subprocess.run(args, cwd=frontend, check=True)

    if not (out_dir / "index.html").is_file():
        print(f"build did not produce {out_dir / 'index.html'}", file=sys.stderr)
        return 1

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(out_dir, dest)

    index = dest / "index.html"
    if not index.is_file():
        print(f"packaged UI missing {index}", file=sys.stderr)
        return 1

    print(f"Packaged UI → {dest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode or 1) from exc
