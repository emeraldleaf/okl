#!/usr/bin/env python3
"""Exploratory, from receipts already committed: does the right lesson's place in a list of ten change
whether the agent acts on it?

§4ax and §4ay gave the right lesson among nine others, at a place seeded per task and repeat
(`replay_list.position`). §4ax's rows record the place; §4ay's do not, and it is recovered from the same
seeded function, which §4ay's sessions used (`replay_one.order`). No model is called.

    python3 evals/list_position.py [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_list as rl
import run_guard

REPO = Path(__file__).resolve().parents[1]
SOURCES = {"4ax": ("replay-list-20261111-0249.json", ("ten_told", "ten_plain")),
           "4ay": ("replay-one-20261111-1355.json", ("ten_plain",))}


def sessions() -> list[dict]:
    """Every list session of §4ax and §4ay: its task, arm, place (1 to 10) and whether it passed."""
    out = []
    for section, (name, arms) in SOURCES.items():
        for row in json.loads((REPO / "evals" / "results" / name).read_text())["rows"]:
            if row["arm"] not in arms:
                continue
            recorded = row.get("position")
            place = recorded if recorded is not None else rl.position(row["pr"], row["rep"])
            out.append({"section": section, "pr": row["pr"], "arm": row["arm"], "rep": row["rep"],
                        "place": place + 1, "place_recorded": recorded is not None, "passed": bool(row["passed"])})
    return out


def tally(rows: list[dict]) -> dict:
    """Passes by place, first against the rest, top three against the rest, and by task."""
    by_place: dict[int, list[bool]] = defaultdict(list)
    by_task: dict[int, list[list]] = defaultdict(list)
    for r in rows:
        by_place[r["place"]].append(r["passed"])
        by_task[r["pr"]].append([r["place"], r["passed"]])

    def share(ok: list[bool]) -> dict:
        return {"passed": sum(ok), "of": len(ok)}
    first = [r["passed"] for r in rows if r["place"] == 1]
    rest = [r["passed"] for r in rows if r["place"] != 1]
    top3 = [r["passed"] for r in rows if r["place"] <= 3]
    lower = [r["passed"] for r in rows if r["place"] > 3]
    return {"sessions": len(rows), "by_place": {str(p): share(v) for p, v in sorted(by_place.items())},
            "first": share(first), "second_to_tenth": share(rest), "top_three": share(top3), "fourth_to_tenth": share(lower),
            "by_task": {str(pr): {"passed": sum(ok for _, ok in v), "of": len(v),
                                  "places_passed": sorted(p for p, ok in v if ok),
                                  "places_failed": sorted(p for p, ok in v if not ok)} for pr, v in sorted(by_task.items())}}


def main() -> int:
    """Print the tally; write the receipt with --receipt."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    run = run_guard.start()
    rows = sessions()
    out = {"what": "exploratory: the right lesson's place in a list of ten, from §4ax's and §4ay's receipts",
           "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "sources": {k: v[0] for k, v in SOURCES.items()},
           "places_recorded": sum(r["place_recorded"] for r in rows), "places_recovered": sum(not r["place_recorded"] for r in rows),
           **tally(rows), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    out = run.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "by_task"}, indent=1))
    for pr, t in out["by_task"].items():
        print(f"  #{pr}: {t['passed']}/{t['of']} passed; passed at {t['places_passed']}, failed at {t['places_failed']}")
    if args.receipt:
        dest = REPO / "evals" / "results" / f"list-position-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
