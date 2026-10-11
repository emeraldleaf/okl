"""Render okl-overview.html to PNG, light and dark, at 2x: python render.py <html> <out-prefix>."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

src, prefix = Path(sys.argv[1]).resolve(), sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=2)
    page.goto(src.as_uri())
    page.evaluate("document.fonts.ready")
    for mode in ("light", "dark"):
        page.evaluate(f"document.documentElement.dataset.mode = '{mode}'")
        page.wait_for_timeout(150)
        # Chrome 87 paints nothing below the viewport in an element screenshot, so the
        # viewport is sized to the whole sheet first.
        h = page.evaluate("Math.ceil(document.getElementById('sheet').getBoundingClientRect().height)")
        page.set_viewport_size({"width": 1200, "height": h})
        page.wait_for_timeout(150)
        loaded = page.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight)")
        page.locator("#sheet").screenshot(path=f"{prefix}-{mode}.png")
        print(mode, "fonts loaded:", sorted(set(loaded)))
    b.close()
