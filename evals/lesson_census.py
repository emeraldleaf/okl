#!/usr/bin/env python3
"""What watches each lesson this repo recorded (REPORT §4ag): drift, CI, or nothing.

    PYTHONPATH=src python3 evals/lesson_census.py [--rev origin/main] [--run-checks]
        # writes evals/results/lesson-census-<stamp>.json

A recorded lesson is one of the store's own, not a seed pack's, that is not retired. Each is in
one class:
- watched: governed files and a stored check, so drift re-runs it when those files change;
- unverified: governed files but no stored check, which drift reports red until one passes;
- checked: a stored check but no governed files, left to CI by the repo's rule (#39);
- unchecked: neither, so nothing re-runs anything for it.

--run-checks runs each checked lesson's stored check once at --rev, as `okl verify` judges it
(exit 0 with the expected text), with §4ae's replayer: a scratch worktree, no OKL_ or
git-location variable. The store is read from a copy. The receipt holds ids, classes, types,
scopes and verdicts, never a lesson's text.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr

from okl.store import RETIRED_STATUSES, Node


def classify(n: Node) -> str:
    """The lesson's class by what could re-run its check (module docstring)."""
    checked = dr.parse_check(n.verified_by) is not None
    if n.files:
        return "watched" if checked else "unverified"
    return "checked" if checked else "unchecked"


def main() -> int:
    """Count the classes, optionally run the checked lessons' checks, and write the receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="origin/main", help="the commit the checks run at")
    ap.add_argument("--run-checks", action="store_true", help="run each checked lesson's check at --rev")
    args = ap.parse_args()
    rev = dr.git("rev-parse", args.rev).strip()
    with dr.store_copy(dr.main_store()) as store:
        live = [n for n in store.all_nodes() if n.status not in RETIRED_STATUSES]
        store.close()
    nodes = [n for n in live if not n.id.startswith("seed:")]
    rows = [{"id": n.id, "class": classify(n), "type": n.type, "scope": n.scope} for n in nodes]
    if args.run_checks:
        with tempfile.TemporaryDirectory() as tmp:
            r = dr.Replayer(Path(tmp))
            try:
                for row, n in zip(rows, nodes, strict=True):
                    check = dr.parse_check(n.verified_by)
                    if row["class"] == "checked" and check:
                        row["verdict"] = r.verdict(rev, *check)
            finally:
                r.close()
    unchecked = [x for x in rows if x["class"] == "unchecked"]
    receipt = {
        "what": "lesson census (REPORT §4ag)",
        "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "code": dr.git("rev-parse", "--short=12", "HEAD").strip(),
        "rev": rev[:12],
        "store": {"recorded": len(rows), "seed": len(live) - len(rows)},
        "classes": dict(Counter(x["class"] for x in rows)),
        "unchecked_by_type": dict(Counter(x["type"] for x in unchecked)),
        "unchecked_by_scope": dict(Counter(x["scope"] for x in unchecked)),
        "checks_at_rev": dict(Counter(x["verdict"] for x in rows if "verdict" in x)) if args.run_checks else None,
        "lessons": rows,
    }
    out = dr.RESULTS / f"lesson-census-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "lessons"}, indent=1))
    print(f"receipt: {out.relative_to(dr.REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
