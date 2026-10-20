"""Render the 4:5 LinkedIn cut of the anatomy sheet, light and dark, at 2x.

    python render_linkedin.py okl-anatomy.html <out-prefix>

The cut keeps the header, the six panels around the ring and the footer, drops the
terminal band and the lower panels, and puts the measured figure in a full-width strip,
so the feed shows the whole image. Same browser setup as render.py.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

STRIP = """
const lower = document.querySelector('section.lower');
document.querySelector('section.example').remove();
const strip = document.createElement('section');
strip.className = 'panel';
strip.style.cssText = 'display:flex;gap:28px;align-items:center;padding:22px 28px;margin-top:18px;';
strip.innerHTML = `
  <div class="stat" style="flex:0 0 auto;margin:0"><span class="big bad">42%</span><span class="arrowto">→</span><span class="big good">7%</span></div>
  <p class="mech" style="margin:0;font-size:15px;line-height:1.45"><b>of attempts repeated a known defect, without the briefing and with it</b>:
  78 of 186 against 13 of 188, over eight A/B runs on tasks built to invite one, one-shot code with the briefing put in the prompt.
  Receipts: evals/REPORT.md §5, finding 7.</p>`;
lower.replaceWith(strip);
// The worked-example callout belongs to the terminal band, which this cut drops.
const callout = [...document.querySelectorAll('section.anatomy *')].find(e => e.children.length === 0 && e.textContent.trim().startsWith('This one:'));
if (callout) (callout.closest('blockquote, aside, .callout, .story, p') || callout).remove();
"""

# The sheet is laid out at a fixed 1200 CSS px and its height follows the text. LinkedIn's
# feed shows a portrait image whole only up to 4:5, so the cut widens the sheet until it
# fits that ratio (shorter lines, shorter sheet); scale the render to 2400 px wide afterwards.
TARGET_RATIO = 1.25

src, prefix = Path(sys.argv[1]).resolve(), sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=2)
    page.goto(src.as_uri())
    page.evaluate("document.fonts.ready")
    page.evaluate(STRIP)
    for width in range(1200, 2001, 40):
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate(f"const s = document.getElementById('sheet'); s.style.width = '{width}px'; s.style.maxWidth = 'none';")
        page.wait_for_timeout(100)
        h = page.evaluate("document.getElementById('sheet').getBoundingClientRect().height")
        if h / width <= TARGET_RATIO:
            break
    else:
        # Past 2000 px the text gets too small to read in a feed; a sheet that still does not
        # fit needs cutting, not widening, so stop rather than save an image that breaks 4:5.
        raise SystemExit(f"sheet is {h:.0f} css px tall at {width} wide (ratio {h / width:.2f}); "
                         f"it cannot meet {TARGET_RATIO}: shorten the anatomy sheet")
    print("sheet width (css px):", width)
    for mode in ("light", "dark"):
        page.evaluate(f"document.documentElement.dataset.mode = '{mode}'")
        page.wait_for_timeout(150)
        h = page.evaluate("Math.ceil(document.getElementById('sheet').getBoundingClientRect().height)")
        page.set_viewport_size({"width": width, "height": h})
        page.wait_for_timeout(150)
        page.locator("#sheet").screenshot(path=f"{prefix}-{mode}.png")
        print(mode, "sheet", width, "x", h, "css px (render is 2x; scale it to 2400 wide afterwards:"
              " python3 -c \"from PIL import Image; ...\" or sips -Z)")
    b.close()
