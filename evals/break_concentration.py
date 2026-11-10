#!/usr/bin/env python3
"""How concentrated past lesson breaks are: of every lesson the real-work keys sorted *not followed*
(§4al's tasks, under both their keys, and §4aq's), how many lessons hold them, and what share the
most-broken ten and twenty hold. The receipt behind #415 and Part 8 of the write-up.

    python3 evals/break_concentration.py [--receipt]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import explain_search as es
import run_guard

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    """Count breaks per lesson over both halves and report the concentration."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    run = run_guard.start()
    breaks: Counter[str] = Counter()
    for half in ("dev", "test"):
        for (_pr, lesson), cls in es.key_of(half).items():
            if cls == "broken":
                breaks[lesson] += 1
    total = sum(breaks.values())
    share = {k: round(sum(n for _, n in breaks.most_common(k)) / total, 3) for k in (10, 20)}
    out = run.stamp({"section": "#415, Part 8", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                     "status": "model-judged keys (§4ao/§4ap for §4al's tasks, §4aq's own), not audited (#394)",
                     "breaks": total, "lessons": len(breaks), "top_share": share,
                     "top20": [{"lesson": lesson, "breaks": n} for lesson, n in breaks.most_common(20)]})
    print(json.dumps({k: out[k] for k in ("breaks", "lessons", "top_share")}))
    if a.receipt:
        dest = REPO / "evals" / "results" / f"break-concentration-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
