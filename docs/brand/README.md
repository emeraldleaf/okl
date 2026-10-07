# okl brand files

| File | Use |
|---|---|
| `okl-logo-light.png` | The logo on light backgrounds (the README header in light mode). |
| `okl-logo-dark.png` | The logo on dark backgrounds (the README header in dark mode). |
| `okl-icon.png` | Small sizes, 64 px and below: the disc alone. It reads on light and dark, so one file serves both. |
| `okl-social-light.png`, `okl-social-dark.png` | GitHub's social preview, 1280×640 (Settings → General → Social preview). |

The mark is a tree's growth rings around a healed fire scar. A tree records every year
in its wood and grows over a wound without erasing it; okl records each lesson and keeps
it on record after the code moves on. The engraved detail does not survive below 64 px,
which is why the small icon drops the frame.

The rings, scar and frame began as images from Google's Gemini (Nano Banana Pro). They
were then recoloured, cut out, given a wider gap in the frame, and lettered in Manrope.

"okl" is set in [Manrope](https://github.com/googlefonts/manrope) ExtraBold, licensed
under the SIL Open Font License 1.1.

These files are excluded from the source distribution (`[tool.hatch.build.targets.sdist]`
in `pyproject.toml`); the README links the logos by URL, so the package on PyPI does not
carry them.
