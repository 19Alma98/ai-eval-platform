"""Record getting-started walkthrough and export docs/images/hero.gif."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_docs_screenshots import (  # noqa: E402
    _wait_experiment_detail,
    _wait_overview,
    _wait_trace_waterfall,
    resolve_demo_context,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_GIF = ROOT / "docs" / "images" / "hero.gif"
VIEWPORT = {"width": 1280, "height": 800}
TARGET_WIDTH = 1200
FPS = 8
FFMPEG = os.getenv("FFMPEG", "/usr/bin/ffmpeg")


def _webm_to_gif(src: Path, dest: Path) -> None:
    palette = src.with_suffix(".palette.png")
    scale = f"fps={FPS},scale={TARGET_WIDTH}:-1:flags=lanczos"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-vf",
            f"{scale},palettegen=stats_mode=diff",
            str(palette),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-i",
            str(palette),
            "-lavfi",
            f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )
    palette.unlink(missing_ok=True)


def main() -> None:
    try:
        project_id, trace_id, experiment_id = resolve_demo_context()
    except Exception as e:
        print(f"Setup failed: {e}", file=sys.stderr)
        sys.exit(1)

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hero-capture-") as tmp:
        video_dir = Path(tmp)
        webm_path: Path | None = None

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=str(video_dir),
                record_video_size=VIEWPORT,
            )
            page = context.new_page()

            try:
                _wait_overview(page, project_id)
                page.wait_for_timeout(4000)
                page.mouse.wheel(0, 400)
                page.wait_for_timeout(3000)

                _wait_trace_waterfall(page, project_id, trace_id)
                page.wait_for_timeout(5000)
                page.mouse.wheel(0, 300)
                page.wait_for_timeout(3000)

                _wait_experiment_detail(page, project_id, experiment_id)
                page.wait_for_timeout(5000)
                page.mouse.wheel(0, 350)
                page.wait_for_timeout(3000)
            except PlaywrightTimeout as e:
                print(f"Capture timed out: {e}", file=sys.stderr)
                context.close()
                browser.close()
                sys.exit(1)

            context.close()
            browser.close()

            videos = list(video_dir.glob("*.webm"))
            if not videos:
                print("No Playwright video file produced.", file=sys.stderr)
                sys.exit(1)
            webm_path = videos[0]

        if webm_path is None or not webm_path.is_file():
            print("Missing recorded webm.", file=sys.stderr)
            sys.exit(1)

        try:
            _webm_to_gif(webm_path, OUT_GIF)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode(errors="replace")
            print(f"ffmpeg failed: {err}", file=sys.stderr)
            sys.exit(1)

    size_mb = OUT_GIF.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUT_GIF} ({size_mb:.2f} MiB)")


if __name__ == "__main__":
    main()
