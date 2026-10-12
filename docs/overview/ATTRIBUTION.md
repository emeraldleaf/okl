# The one-page overview

`okl-overview.html` is the source; `okl-overview-light.png` and `okl-overview-dark.png` are
its renders, embedded at the top of the README's "How it works". Edit the HTML, then
re-render both from this folder:

    python render.py okl-overview.html okl-overview

`okl-anatomy.html` is the longer sheet: one lesson followed all the way round, with real
okl output in its terminal band. It renders the same way:

    python render.py okl-anatomy.html okl-anatomy

Its terminal lines are okl's own output from a throwaway repo, trimmed where marked (…) and
annotated with `#` notes. When okl's wording changes, run the story again and copy the new
lines in rather than editing them by hand.

`render.py` drives a local Chrome through Playwright (`pip install playwright`, and
`channel="chrome"` uses the system browser, so no browser download). Look at both renders
before committing: the PNGs are what people read, and nothing checks them against the HTML.

## Attribution

- **Fonts**: Space Grotesk, Inter and IBM Plex Mono, each under the SIL Open Font License
  1.1, copied from emeraldleaf.dev's self-hosted set (2026-10-11).
- **Icons**: Lucide, from `lucide-static@0.460.0` (https://lucide.dev), ISC License, inlined
  unmodified as `<symbol>`s in the HTML.
- **Logo**: okl's own, from `docs/brand/`.
