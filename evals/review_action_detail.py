#!/usr/bin/env python3
"""REPORT §4ap's misses and raises, read after the run as its rule requires; not pre-registered.

    python3 evals/review_action_detail.py
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lesson_review as lr
import realwork_label as rl
import realwork_reach as rr
import review_action as ra
import review_state_detail as rsd

RECEIPT = rr.REPO / "evals" / "results" / "review-action-20261108-2050.json"


def split(rows: list[dict], name: str, chosen: list[dict]) -> dict:
    """What the review did on `chosen`, a subset of the task rows."""
    return {"group": name, "tasks": len(chosen), "of_tasks": len(rows), "calling_for_action": sum(len(r["needed"]) for r in chosen),
            "confirmed": sum(len(r["confirmed"]) for r in chosen), "raised": sum(len(r["named"]["review"]) for r in chosen),
            "wrong": sum(len(r["wrong"]) for r in chosen)}


def main() -> int:
    """Write the detail receipt."""
    receipt = json.loads(RECEIPT.read_text())
    rows = receipt["per_task"]
    dev, test = lr.load_tasks()
    tasks = {t["pr"]: t for t in dev}
    key, texts, answers = rsd.load(ra.KEY), rl.lesson_text(rr.SNAPSHOT), ra.load_answers()
    labels = ra.labels_for(dev, texts)
    verdict = lambda pr, i: labels[(pr, i)].get("verdict")   # noqa: E731 - read four times below
    misses = [{"pr": r["pr"], "lesson": i, "parts": len(ra.parts_of(ra.whole(tasks[r["pr"]]))), "review_said": r["words"][i],
               "key_state": r["states"][i], "key_why": key[(r["pr"], i)]["why"]} for r in rows for i in r["missed"]]
    wrong_no = sum(1 for r in rows for i in r["wrong"] if verdict(r["pr"], i) == "no")
    related = sum(1 for r in rows for i in r["unresolved"] if verdict(r["pr"], i) == "related")
    wrong, unresolved = sum(len(r["wrong"]) for r in rows), sum(len(r["unresolved"]) for r in rows)
    long_prs = {t["pr"] for t in dev if len(ra.whole(t)) > rl.CUT}
    on_388 = next(t for t in test if t["pr"] == ra.LEDGER_PR)
    n_388 = len(ra.parts_of(ra.whole(on_388)))
    ledger = [json.loads(line)["lesson"] for line in lr.LEDGER.read_text().splitlines() if line.strip()]
    result = receipt["result"]
    below = result["reach"] - result["reach_boot95"][0]
    room = result["reach"] - ra.REACH_BAR
    out = {"section": "4ap misses and raises, not pre-registered", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": rl.git("rev-parse", "HEAD").strip(),
           "status": "model-judged, not yet audited (#394)", "from_receipt": RECEIPT.name, "misses": misses,
           "missed_by_word": {w: sum(1 for m in misses if m["review_said"] == w) for w in ra.WORDS},
           "raises": {"total": sum(len(r["named"]["review"]) for r in rows), "confirmed": sum(len(r["confirmed"]) for r in rows),
                      "wrong_labelled_no": wrong_no, "wrong_already_followed": wrong - wrong_no, "unresolved_labelled_related": related, "unresolved_other": unresolved - related},
           "per_pr_median": {"confirmed": statistics.median(len(r["confirmed"]) for r in rows), "wrong": statistics.median(len(r["wrong"]) for r in rows),
                             "unresolved": statistics.median(len(r["unresolved"]) for r in rows)},
           "raised_on_tasks_with_no_action": {str(r["pr"]): len(r["named"]["review"]) for r in rows if not r["needed"]},
           "by_length": [split(rows, "long, labelled again", [r for r in rows if r["pr"] in long_prs]), split(rows, "short", [r for r in rows if r["pr"] not in long_prs])],
           "ledger_by_part_on_388": {i: [answers[(ra.LEDGER_PR, p, i)]["answer"] for p in range(n_388)] for i in ledger},
           "lessons_for_the_bar_at_this_reach": {"note": "the interval's width scaled by the square root of the sample, a rough estimate", "had": result["calling_for_action"],
                                                 "needed": round(result["calling_for_action"] * (below / room) ** 2)}}
    dest = rr.REPO / "evals" / "results" / f"review-action-detail-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "misses"}, indent=1))
    print(f"receipt: {dest.relative_to(rr.REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
