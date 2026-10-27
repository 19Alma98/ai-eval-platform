# Docs images

| File | Source |
|------|--------|
| `hero.gif` | Manual screen recording (30–60s). See below. |
| `ui-overview.png` | `scripts/capture_docs_screenshots.py` |
| `ui-trace-waterfall.png` | same |
| `ui-experiment.png` | same |

## Regenerate PNGs

1. Start UI: `uv run opengrade ui` (judge configured if you need experiment scores).
2. Seed: run `scripts/getting_started_core.py` then `scripts/getting_started_bonus.py`.
3. From repo root (Playwright from `frontend/`):

```bash
cd frontend && npx playwright install chromium
cd ..
pip install playwright
playwright install chromium
OPENGRADE_UI_URL=http://127.0.0.1:8000 python scripts/capture_docs_screenshots.py
```

Or with uv and the frontend dependency group:

```bash
cd frontend && npm exec -- playwright install chromium
cd ..
uv run --directory frontend --with playwright \
  python ../scripts/capture_docs_screenshots.py
```

## Re-record hero.gif

1. Start UI + run Core (and optionally Bonus).
2. Record 30–60s: Overview → Traces waterfall → Experiments detail.
3. Export GIF (~800–1200px wide), replace `docs/images/hero.gif`.
