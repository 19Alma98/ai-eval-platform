"""Record the README walkthrough and export docs/images/hero.gif.

Needs a running UI seeded by ``scripts/portfolio_demo.py`` (baseline + candidate
experiment) and ``scripts/live_run_demo.py`` (live answers) in the same project.

Usage (UI on http://127.0.0.1:8000, ffmpeg on PATH)::

    uv run --with playwright playwright install chromium
    uv run --with playwright python scripts/capture_hero_gif.py

Frames come from the Chrome screencast (lossless PNG, only on change), so the GIF
stays sharp and small: static screens cost one frame, not one per tick.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_GIF = ROOT / "docs" / "images" / "hero.gif"
UI = os.getenv("OPENGRADE_UI_URL", "http://127.0.0.1:8000").rstrip("/")
PROJECT_SLUG = os.getenv("OPENGRADE_PROJECT_SLUG", "hr-it-assistant")
QUESTION = os.getenv("OPENGRADE_HERO_QUESTION", "How many PTO days")
VIEWPORT = {"width": 1280, "height": 800}
TARGET_WIDTH = 960
FPS = 10
FFMPEG = os.getenv("FFMPEG", "ffmpeg")
CHROMIUM = os.getenv("CHROMIUM_EXECUTABLE")  # optional: use a preinstalled Chromium

# Fake cursor + caption pill: headless screenshots show neither the pointer nor context.
OVERLAY_JS = """
(() => {
  const install = () => {
    if (document.getElementById('og-cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #og-cursor { position: fixed; z-index: 2147483647; pointer-events: none;
        left: 0; top: 0; width: 22px; height: 22px; transform: translate(640px, 400px); }
      #og-ripple { position: fixed; z-index: 2147483646; pointer-events: none; width: 34px;
        height: 34px; margin: -17px 0 0 -17px; border-radius: 50%;
        background: rgba(37, 99, 235, .35); opacity: 0; }
      #og-caption { position: fixed; z-index: 2147483645; left: 50%; bottom: 28px;
        transform: translateX(-50%); display: none; pointer-events: none;
        align-items: center; gap: 12px;
        padding: 12px 22px; border-radius: 999px; background: rgba(17, 24, 39, .92);
        color: #fff; font: 600 19px/1.2 system-ui, -apple-system, 'Segoe UI', sans-serif;
        box-shadow: 0 10px 30px rgba(0, 0, 0, .25); white-space: nowrap; }
      #og-caption b { display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; border-radius: 50%; background: #2563eb; font-size: 14px; }`;
    document.head.appendChild(style);
    const cursor = document.createElement('div');
    cursor.id = 'og-cursor';
    cursor.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24">
      <path d="M4 2l16 10-7 1.5L9.5 21z" fill="#111827" stroke="#fff"
        stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    const ripple = document.createElement('div');
    ripple.id = 'og-ripple';
    const caption = document.createElement('div');
    caption.id = 'og-caption';
    document.body.append(cursor, ripple, caption);
    const pos = window.__ogPos || { x: 640, y: 400 };
    cursor.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
    if (window.__ogCaption) window.__ogSetCaption(...window.__ogCaption);
  };
  window.__ogSetCaption = (step, text) => {
    window.__ogCaption = [step, text];
    const el = document.getElementById('og-caption');
    if (!el) return;
    el.style.display = text ? 'inline-flex' : 'none';
    el.innerHTML = step ? `<b>${step}</b><span>${text}</span>` : `<span>${text}</span>`;
  };
  document.addEventListener('mousemove', (e) => {
    window.__ogPos = { x: e.clientX, y: e.clientY };
    const c = document.getElementById('og-cursor');
    if (c) c.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
  }, true);
  document.addEventListener('mousedown', (e) => {
    const r = document.getElementById('og-ripple');
    if (!r) return;
    r.style.left = e.clientX + 'px';
    r.style.top = e.clientY + 'px';
    r.animate([{ opacity: 1, transform: 'scale(.4)' }, { opacity: 0, transform: 'scale(1.4)' }],
      { duration: 450, easing: 'ease-out' });
  }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
  new MutationObserver(install)
    .observe(document.documentElement, { childList: true, subtree: true });
})();
"""


def _get_json(path: str) -> object:
    req = urllib.request.Request(f"{UI}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def resolve_demo_context() -> tuple[str, str]:
    """Return (project_id, candidate_experiment_name) for the portfolio demo data."""
    projects = _get_json("/api/v1/projects")
    assert isinstance(projects, list)
    project = next((p for p in projects if p.get("slug") == PROJECT_SLUG), None)
    if not project:
        raise RuntimeError(f"No project {PROJECT_SLUG!r}. Run scripts/portfolio_demo.py first.")
    experiments = _get_json(f"/api/v1/projects/{project['id']}/experiments")
    assert isinstance(experiments, list)
    candidate = next((e for e in experiments if e.get("baseline_experiment_id")), None)
    if not candidate:
        raise RuntimeError("No experiment with a baseline. Run scripts/portfolio_demo.py first.")
    return project["id"], candidate["name"]


class Director:
    """Drives the page like a person: visible cursor, eased moves, captions."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.x, self.y = 640.0, 400.0

    async def caption(self, step: str, text: str) -> None:
        await self.page.evaluate("([s, t]) => window.__ogSetCaption(s, t)", [step, text])

    async def pause(self, ms: int) -> None:
        await self.page.wait_for_timeout(ms)

    async def move_to(self, locator, *, steps: int = 18) -> None:
        await locator.wait_for(state="visible", timeout=20_000)
        box = await locator.bounding_box()
        assert box is not None
        tx, ty = box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)  # smoothstep
            await self.page.mouse.move(self.x + (tx - self.x) * e, self.y + (ty - self.y) * e)
            await self.page.wait_for_timeout(16)
        self.x, self.y = tx, ty

    async def click(self, locator, *, settle: int = 900) -> None:
        await self.move_to(locator)
        await self.pause(180)
        await self.page.mouse.down()
        await self.page.mouse.up()
        await self.page.wait_for_load_state("networkidle")
        await self.pause(settle)

    async def scroll_to(self, locator, *, offset: int = 90, ms: int = 700) -> None:
        await locator.wait_for(state="attached", timeout=20_000)
        await locator.evaluate(
            """(el, [offset, ms]) => new Promise((done) => {
                const from = window.scrollY;
                const to = from + el.getBoundingClientRect().top - offset;
                const t0 = performance.now();
                const tick = (now) => {
                  const t = Math.min(1, (now - t0) / ms);
                  window.scrollTo(0, from + (to - from) * t * t * (3 - 2 * t));
                  t < 1 ? requestAnimationFrame(tick) : done();
                };
                requestAnimationFrame(tick);
            })""",
            [offset, ms],
        )


async def walkthrough(d: Director, project_id: str, candidate: str) -> None:
    page = d.page
    main = page.locator("main")
    nav = page.locator("aside, nav").first

    # 1 — Overview: release + production health at a glance.
    await page.goto(f"{UI}/overview?project={project_id}", wait_until="networkidle")
    await page.get_by_role("heading", name="Overview").wait_for()
    await d.caption("1", "Is the next version safe to ship? One page answers it")
    await d.pause(500)
    await d.move_to(page.get_by_text("Before release", exact=True))
    await d.pause(1100)
    await d.move_to(page.get_by_text("Latest experiment vs baseline"))
    await d.pause(1300)

    # 2 — Traces: the full RAG call, step by step.
    await d.caption("2", "Trace every call: query → retrieved chunks → prompt → answer")
    views = main.get_by_role("navigation", name="Production views")
    await d.click(nav.get_by_role("link", name="Production"), settle=300)
    await d.click(views.get_by_role("link", name="Traces"), settle=700)
    await d.click(main.locator("tbody tr").first, settle=1200)
    await d.move_to(main.get_by_text("Retrieved chunks"))
    await d.pause(1000)
    await d.click(page.get_by_role("tab", name="Timeline"), settle=1500)

    # 3 — Experiment: deterministic metrics + LLM judges on a gold test set.
    await d.caption("3", "Score every answer: retrieval metrics + LLM judges")
    await d.click(nav.get_by_role("link", name="Experiments"), settle=600)
    await d.click(main.get_by_text(candidate, exact=True).first, settle=1600)
    await d.scroll_to(main.get_by_role("heading", name="Answers"), offset=70, ms=380)
    await d.click(main.get_by_text(QUESTION).first, settle=1500)

    # 4 — Compare: what got worse, with confidence intervals and both answers.
    await d.caption("4", "Compare with the baseline: see exactly what regressed")
    await d.scroll_to(page.locator("body"), offset=0, ms=320)
    await d.click(main.get_by_role("link", name="Compare").first, settle=1500)
    await d.scroll_to(main.get_by_text("Answers side by side"), offset=80, ms=380)
    await d.click(main.get_by_text("Got worse", exact=True), settle=1600)

    # 5 — Quality gate: one verdict, same rules as `opengrade check` in CI.
    await d.caption("5", "Gate the release, in the UI or in CI with `opengrade check`")
    await d.click(nav.get_by_role("link", name="Quality gate"), settle=500)
    run = main.get_by_role("button", name="Run quality gate")
    await d.scroll_to(run, offset=560, ms=380)
    await d.click(run, settle=500)
    verdict = main.get_by_text("Not ready to ship").or_(main.get_by_text("Ready to ship")).first
    await verdict.wait_for(timeout=20_000)
    await d.scroll_to(verdict, offset=110, ms=380)
    await d.move_to(verdict)
    await d.pause(2000)

    # 6 — Production: hallucination caught by the judge, one click to a test case.
    await d.caption("6", "Catch hallucinations in production, turn them into test cases")
    await d.click(nav.get_by_role("link", name="Production"), settle=300)
    await d.click(views.get_by_role("link", name="Live answers"), settle=600)
    await d.click(main.get_by_text("Failing", exact=True).last, settle=600)
    await d.click(main.locator("tbody tr").first, settle=1100)
    await d.move_to(main.get_by_text("Not in documents").first)
    await d.pause(1100)
    await d.move_to(main.get_by_role("button", name="Add to test set"))
    await d.pause(2000)


async def record(frames_dir: Path, project_id: str, candidate: str) -> list[tuple[Path, float]]:
    frames: list[tuple[Path, float]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROMIUM or None)
        context = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        await context.add_init_script(OVERLAY_JS)
        page = await context.new_page()
        cdp = await context.new_cdp_session(page)

        async def on_frame(evt: dict) -> None:
            path = frames_dir / f"{len(frames):05d}.png"
            path.write_bytes(base64.b64decode(evt["data"]))
            frames.append((path, float(evt["metadata"]["timestamp"])))
            await cdp.send("Page.screencastFrameAck", {"sessionId": evt["sessionId"]})

        cdp.on("Page.screencastFrame", lambda evt: asyncio.ensure_future(on_frame(evt)))
        await page.goto(f"{UI}/overview?project={project_id}", wait_until="networkidle")
        await cdp.send(
            "Page.startScreencast",
            {"format": "png", "maxWidth": VIEWPORT["width"], "maxHeight": VIEWPORT["height"]},
        )
        try:
            await walkthrough(Director(page), project_id, candidate)
        except Exception:
            failed = ROOT / "hero-capture-failed.png"
            await page.screenshot(path=str(failed))
            print(f"Walkthrough failed at {page.url} (screenshot: {failed})", file=sys.stderr)
            raise
        finally:
            await cdp.send("Page.stopScreencast")
            await context.close()
            await browser.close()
    return frames


def frames_to_gif(frames: list[tuple[Path, float]], dest: Path, workdir: Path) -> None:
    frames = sorted(frames, key=lambda f: f[1])
    concat = workdir / "frames.txt"
    lines = []
    for (path, ts), (_, nxt) in zip(
        frames, frames[1:] + [(None, frames[-1][1] + 2.0)], strict=True
    ):
        lines.append(f"file '{path}'\nduration {max(nxt - ts, 0.001):.3f}")
    lines.append(f"file '{frames[-1][0]}'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")

    palette = workdir / "palette.png"
    scale = f"fps={FPS},scale={TARGET_WIDTH}:-1:flags=lanczos"
    src = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat)]
    subprocess.run(
        [*src, "-vf", f"{scale},palettegen=max_colors=128:stats_mode=full", str(palette)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            *src,
            "-i",
            str(palette),
            "-lavfi",
            f"{scale}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle",
            "-loop",
            "0",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def main() -> None:
    try:
        project_id, candidate = resolve_demo_context()
    except Exception as e:
        print(f"Setup failed: {e}", file=sys.stderr)
        sys.exit(1)

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hero-capture-") as tmp:
        workdir = Path(tmp)
        frames = asyncio.run(record(workdir, project_id, candidate))
        if len(frames) < 10:
            print(f"Only {len(frames)} frames captured.", file=sys.stderr)
            sys.exit(1)
        try:
            frames_to_gif(frames, OUT_GIF, workdir)
        except subprocess.CalledProcessError as e:
            print(f"ffmpeg failed: {(e.stderr or b'').decode(errors='replace')}", file=sys.stderr)
            sys.exit(1)

    duration = frames[-1][1] - frames[0][1]
    size_mb = OUT_GIF.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUT_GIF} ({size_mb:.2f} MiB, {len(frames)} frames, ~{duration:.0f}s)")


if __name__ == "__main__":
    main()
