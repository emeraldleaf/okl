#!/usr/bin/env python3
"""What #318's change to the watched lessons' files costs (REPORT §4ah): the re-verifications drift
would have asked for on this repository's history, with each lesson's governed files as the
snapshot had them before #318 and as it has them after, counted without running any check.

    PYTHONPATH=$PWD/src python3 evals/drift_widen_cost.py [--after <commit>]
        # writes evals/results/drift-widen-cost-<stamp>.json

The two file lists are the committed snapshots: BEFORE's (main before #318) and AFTER's (HEAD by
default). Both are applied to the whole window, so "before" is what today's lists would have
cost, not what was paid: lessons were recorded and widened along the way. A lesson AFTER no
longer lists governs nothing there. The window is every commit of BEFORE since the snapshot was
first committed (SINCE), counted two ways, as a floor and a ceiling on the step:
- per merge into main (a first-parent commit): a merge whose diff against its first parent
  touches a lesson's files re-verifies that lesson at least once before it lands;
- per commit (every commit that is not a merge): a lesson re-verified after each commit that
  touches its files.
"Lesson re-checks" counts lesson and unit pairs; "units that re-verify" counts units that touch
any watched lesson's files, which is when a person pays the step at all. The test is
drift_replay.differs, drift's own.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr

SINCE = "61b567c"   # "Commit this repo's drift snapshot, so CI checks drift for real", 2026-09-25
BEFORE = "3af67a8"  # main before #318


def count(units: list[str], lists: dict[str, dict[str, list[str]]]) -> dict:
    """Per lesson and in all, how many of `units` touch each side's governed files."""
    per = {lid: dict.fromkeys(lists, 0) for lid in lists["before"]}
    touched = dict.fromkeys(lists, 0)
    for x in units:
        for side, files in lists.items():
            hit = [lid for lid, f in files.items() if dr.differs(f"{x}^1", x, f)]
            for lid in hit:
                per[lid][side] += 1
            touched[side] += bool(hit)
    return {"units": len(units), "per_lesson": per, "touched": touched,
            "lesson_rechecks": {side: sum(v[side] for v in per.values()) for side in lists}}


def main() -> int:
    """Count both ways and write the receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", default="HEAD", help="the commit whose snapshot holds #318's files")
    args = ap.parse_args()
    before = {lid: dr.governs(rule) for lid, rule in dr.snapshot(BEFORE).items() if dr.governs(rule)}
    after_rev = dr.git("rev-parse", "--verify", "-q", f"{args.after}^{{commit}}").strip()
    now = dr.snapshot(after_rev) if after_rev else {}
    if not now:   # an unknown revision, or one with no snapshot, would read as every lesson cleared
        sys.exit(f"drift_widen_cost: {args.after!r} is not a commit with an okl-drift.json")
    after = {lid: dr.governs(now.get(lid) or {}) for lid in before}
    lists = {"before": before, "after": after}
    merges = count(dr.git("rev-list", "--first-parent", f"{SINCE}..{BEFORE}").split(), lists)
    commits = count(dr.git("rev-list", "--no-merges", f"{SINCE}..{BEFORE}").split(), lists)
    receipt = {
        "section": "§4ah", "what": "re-verifications drift asks for, governed files before and after #318",
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "code": dr.git("rev-parse", "HEAD").strip(),
        "since": dr.git("rev-parse", SINCE).strip(), "before": dr.git("rev-parse", BEFORE).strip(),
        "after": dr.git("rev-parse", args.after).strip(), "files": lists,
        "per_merge": merges, "per_commit": commits,
    }
    out = Path(__file__).resolve().parent / "results" / f"drift-widen-cost-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    for name, c in (("merges", merges), ("commits", commits)):
        print(f"{c['units']} {name} {SINCE}..{BEFORE}: lesson re-checks {c['lesson_rechecks']['before']} -> "
              f"{c['lesson_rechecks']['after']}; {name} that re-verify {c['touched']['before']} -> {c['touched']['after']}")
    for lid in sorted(before):
        m, c = merges["per_lesson"][lid], commits["per_lesson"][lid]
        mark = " " if before[lid] == after[lid] else "*"
        print(f" {mark} {lid:22} merges {m['before']:4} -> {m['after']:4}   commits {c['before']:4} -> {c['after']:4}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
