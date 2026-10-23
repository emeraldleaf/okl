"""Render a sheet (okl-overview.html, okl-anatomy.html) to PNG, light and dark, at 2x.

    uv run --with playwright --with pillow python render.py <html> <out-prefix>

Chrome paints nothing below the viewport in a screenshot, and a viewport as tall as the
anatomy sheet (about 3,500 CSS px, at 2x) crashes the tab on a current Chrome: the previous
recipe, which sized the viewport to the sheet, hung at the sheet's screenshot. The sheet is
therefore captured in viewport-sized tiles and stitched. Uses the installed Google Chrome
(channel "chrome"), so nothing is downloaded.
"""
import io
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

WIDTH, TILE, SCALE = 1200, 800, 2

src, prefix = Path(sys.argv[1]).resolve(), sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": WIDTH, "height": TILE}, device_scale_factor=SCALE)
    page.goto(src.as_uri())
    page.evaluate("document.fonts.ready")
    for mode in ("light", "dark"):
        page.evaluate(f"document.documentElement.dataset.mode = '{mode}'")
        page.wait_for_timeout(250)
        box = page.evaluate("(() => { const r = document.getElementById('sheet').getBoundingClientRect();"
                            " return {x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height}; })()")
        x0, y0, w, h = int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])
        out = Image.new("RGB", (w * SCALE, h * SCALE))
        y = 0
        while y < h:
            page.evaluate(f"window.scrollTo(0, {y0 + y})")
            page.wait_for_timeout(120)
            # The last tile cannot scroll the sheet's row to the top of the viewport, so the
            # row's position is read back rather than assumed.
            top = (y0 + y) - page.evaluate("window.scrollY")
            take = min(TILE - top, h - y)
            shot = Image.open(io.BytesIO(page.screenshot()))
            out.paste(shot.crop((x0 * SCALE, top * SCALE, (x0 + w) * SCALE, (top + take) * SCALE)), (0, y * SCALE))
            y += take
        out.save(f"{prefix}-{mode}.png")
        print(mode, "sheet", w, "x", h, "css px ->", out.size)
    b.close()
