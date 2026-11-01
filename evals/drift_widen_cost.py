#!/usr/bin/env python3
"""What #318's change to the watched lessons' files costs (REPORT §4ag): the re-verifications drift
would have asked for on this repository's history, with each lesson's governed files as the
snapshot had them and as #318 sets them, counted without running any check.

    PYTHONPATH=$PWD/src python3 evals/drift_widen_cost.py   # writes evals/results/drift-widen-cost-<stamp>.json

The unit is a merge into main, a first-parent commit of UNTIL since the snapshot was first
committed (SINCE): under the drift order, one whose diff against its first parent touches a
lesson's governed files re-verifies that lesson at least once before it merges (a review round
that touches them again re-verifies it again, so this is a floor). "Lesson re-checks" counts
lesson and merge pairs; "merges that re-verify" counts merges that touch any watched lesson's
files, which is when a person pays the step at all. The test is drift_replay.differs, drift's own.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr

SINCE = "61b567c"   # "Commit this repo's drift snapshot, so CI checks drift for real", 2026-09-25
UNTIL = "3af67a8"   # main after #325
# #318: lessons whose check CI already runs lose their files (#39); the rest govern what their
# claim depends on. Any watched lesson not named here keeps its files.
CHANGED = {
    "n_71c09abf3f37": "",
    "n_b74bad29fd87": "",
    "n_be9f13d587b1": "",
    "n_e635fd921086": "",
    "doc-check-defaults": "README.md,src/okl/core.py,src/okl/cli/,src/okl/client.py,src/okl/service.py",
    "docs-agent-neutral": "README.md,docs/",
    "n_d45d7bf64896": "README.md,CHANGELOG.md,docs/",
    "n_7e50e3588bcd": "tests/,pyproject.toml",
}


def main() -> int:
    """Count both ways and write the receipt."""
    before = {lid: dr.governs(rule) for lid, rule in dr.snapshot(UNTIL).items() if dr.governs(rule)}
    after = {lid: dr.governs({"files": CHANGED.get(lid, ",".join(files))}) for lid, files in before.items()}
    merges = dr.git("rev-list", "--first-parent", "--reverse", f"{SINCE}..{UNTIL}").split()
    per = {lid: {"before": 0, "after": 0} for lid in before}
    any_before = any_after = 0
    for x in merges:
        parent = f"{x}^1"
        hit_b = {lid for lid, f in before.items() if dr.differs(parent, x, f)}
        hit_a = {lid for lid, f in after.items() if dr.differs(parent, x, f)}
        for lid in hit_b:
            per[lid]["before"] += 1
        for lid in hit_a:
            per[lid]["after"] += 1
        any_before += bool(hit_b)
        any_after += bool(hit_a)
    total_b = sum(v["before"] for v in per.values())
    total_a = sum(v["after"] for v in per.values())
    receipt = {
        "section": "§4ag", "what": "re-verifications drift asks for, governed files before and after #318",
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "code": dr.git("rev-parse", "HEAD").strip(),
        "since": dr.git("rev-parse", SINCE).strip(), "until": dr.git("rev-parse", UNTIL).strip(),
        "merges": len(merges), "files": {"before": before, "after": after},
        "per_lesson": {lid: per[lid] | {"changed": lid in CHANGED} for lid in sorted(per)},
        "lesson_rechecks": {"before": total_b, "after": total_a},
        "merges_that_reverify": {"before": any_before, "after": any_after},
    }
    out = Path(__file__).resolve().parent / "results" / f"drift-widen-cost-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"{len(merges)} merges {SINCE}..{UNTIL}")
    for lid in sorted(per):
        mark = "*" if lid in CHANGED else " "
        print(f" {mark} {lid:22} {per[lid]['before']:4} -> {per[lid]['after']:4}")
    print(f"lesson re-checks {total_b} -> {total_a}; merges that re-verify {any_before} -> {any_after} of {len(merges)}")
    print(f"wrote {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
