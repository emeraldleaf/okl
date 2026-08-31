---
description: Geospatial ML rules — rslearn/OlmoEarth, label quality, spatial CV, storage
paths: ["**/*.py", "**/*.yaml", "**/*.yml"]
---

# Geospatial ML (rslearn / OlmoEarth / Sentinel / remote sensing)

> Ported from the geospatial pipeline method.md. Stack: rslearn, OlmoEarth, Sentinel-1/2, STAC,
> Planetary Computer, GDAL. Each rule is a dated defect (error # from method.md).

## Label quality — the failures that compile

- **Don't rasterize every polygon as the positive class** (error #1: ~45% of positive labels were wrong — urban/agriculture/upland/water taught as geospatial). Inspect what a label layer actually contains before fitting to it.
- **Labels and imagery must be time-matched** (error #3: NAIP 2020 labels fit against Sentinel-2 2024 = 4-year gap of self-inflicted label noise). Check the acquisition date in the source metadata of *both* sides.
- **A model scored against wrong labels produces a meaningless metric** — verify label provenance before trusting any F1/AUC/κ.

## Spatial cross-validation

- **Unshuffled KFold on a spatial grid leaks nothing and looks broken** (error #11: AUC 0.23 looked like a broken encoder; it was unshuffled KFold on a spatial grid — shuffled gave 0.85). Use spatial-block or shuffled CV; refuse a convenient bad number until you've ruled out the split.
- **Count/plot points on a map before trusting a public dataset's coordinate order** (error #12: `Virgin_River` rows had x/y transposed — 119 points in the wrong hemisphere).

## rslearn / OlmoEarth scaffolding — verify, don't assert from memory

- **Import every `class_path` before writing it into a config** (error #14: 5 of 23 class_paths didn't exist — every class name right, every module path wrong, written from memory, never imported; they fail at runner startup on a rented GPU). A mechanical `check-scaffold-classpaths.sh` that imports all of them is the gate.
- **Verify materialize wrote files — never trust the exit code** (error #15: `rslearn dataset materialize` exited 0 having written zero files; `NotImplementedError` on all 238 windows swallowed into a worker pool). `verify_materialized()` checks the rasters are on disk.
- **`num_classes` = max crosswalk id + 1 when class 0 is reserved** (error #18: `num_classes: 4` crashed `Target 4 is out of bounds` because the crosswalk emits 4 real classes and `zero_is_invalid` reserves class 0 → needs 5). A `test_class_scheme_contract.py` asserts this mechanically.
- **Decoders on a temporal cube must read the true last-two axes** (error #19: `SegmentationPoolingDecoder` read `image.shape[1:3]` = `(timesteps, H)` on a 4-D `[bands, timesteps, H, W]` input, predicting 12×2 against a 2×2 target). Use a temporal-aware adapter; catch it with a laptop dry-run, not a GPU.

## Storage & temp dirs (cloud-optimized geotiff / GDAL)

- **Budget the tile store, not the output** (error #16: "~1.2 GB" estimate was right for materialized chips, ~10× low for `ingest` which pulls whole 110 km granules → 11 GB tile store).
- **Redirect EVERY temp mechanism, not the first one** (errors #16/#17: `TMPDIR` on the boot disk filled `/` to zero; moving `TMPDIR` to the data drive still leaked 2.8 GB to `/` because **GDAL keeps its own `CPL_TMPDIR`**). Set both `TMPDIR` and `CPL_TMPDIR` to the data drive.

## Novelty & prior art (the claim is falsifiable)

- **Audit the literature adversarially before building** (error #5: a "nobody has mapped X" novelty claim was later found to be falsified by prior art — the geospatial repo's method.md attributes this to Evangelista et al. 2018 2-epoch change maps and a 2018 CO-RIP basin-wide RF study at κ 0.80, both found *after* building; these citations are transcribed from method.md and **not independently re-verified here — confirm against the literature before relying on them**). Run `/paper-audit` looking for reasons a paper *refutes* your novelty claim.
- **Run the control before the experiment** — a bad number on the interesting question is uninterpretable (broken pipeline / too few labels / real effect all predict the same failure).
- **Report the result that came out** (error #4: the mean-pooling defect was real, fixing it moved F1 0.021→0.065 vs RF 0.701 — the hypothesis was wrong, and was published wrong). A real defect is not proof it was the cause.
