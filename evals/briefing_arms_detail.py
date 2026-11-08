#!/usr/bin/env python3
"""REPORT §4am's and §4an's detail, computed after their runs and not pre-registered.

What adopting both passing arms would cost together, the share of each arm's added lessons that
were needed, the new lessons per changed file of the two arms that read the change, and the warm
model's fallbacks. Deterministic from the two receipts, the labels and the tasks.

    python3 evals/briefing_arms_detail.py evals/results/briefing-arms-<stamp>.json \
        evals/results/path-triggers-<stamp>.json
"""
from __future__ import annotations

import json
import random
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import realwork_reach as rr

PAIR = "S10+R"


def main(path: str, triggers_path: str) -> int:
    """Write the detail receipt beside §4am's."""
    receipt = json.loads(Path(path).read_text())
    labels = {}
    for line in rr.LABELS.read_text().splitlines():
        r = json.loads(line)
        labels[(r["pr"], r["lesson"])] = r.get("verdict")
    tasks = {t["pr"]: t for t in (json.loads(x) for x in rr.TASKS.read_text().splitlines() if x.strip())}
    rows = [{**x, "named": {**x["named"], PAIR: sorted(set(x["named"]["S10"]) | set(x["named"]["R"]))}}
            for x in receipt["per_task"]]
    pair = {}
    for h in ("test", "dev"):
        half = [x for x in rows if x["half"] == h]
        rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
        pair[h] = {**ba.tally(half, PAIR, labels, rng),
                   "briefing_size_median": statistics.median(len(x["named"][PAIR]) for x in half)}
    test = [x for x in rows if x["half"] == "test"]
    added_needed = {}
    for arm in ("S10", "R", "D"):
        added = [set(x["named"][arm]) - set(x["named"]["base"]) for x in test]
        needed = sum(len(s & set(x["needed"])) for x, s in zip(test, added, strict=True))
        total = sum(len(s) for s in added)
        added_needed[arm] = {"added": total, "needed": needed, "share": round(needed / max(1, total), 3)}
    per_file = [len(set(x["named"]["D"]) - set(x["named"]["base"])) / max(1, len(tasks[x["pr"]]["paths"])) for x in test]
    p_rows = [x for x in json.loads(Path(triggers_path).read_text())["per_task"] if x["half"] == "test"]
    p_per_file = [len(set(x["named"]["P"]) - set(x["named"]["base"])) / max(1, len(tasks[x["pr"]]["paths"])) for x in p_rows]
    fell_back = [int(s.split(": ")[1].split()[0]) for s in receipt["warm_fell_back_after_every_try"]]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rr.REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    out = {"section": "4am and 4an detail, not pre-registered", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": head,
           "status": "model-judged, not yet audited (#394)", "from_receipts": [Path(path).name, Path(triggers_path).name],
           "pair_S10_and_R": pair, "added_and_needed_on_test": added_needed,
           "diff_on_test": {"new_lessons_per_changed_file_median": round(statistics.median(per_file), 2),
                            "changed_files_per_task_median": statistics.median(len(tasks[x["pr"]]["paths"]) for x in test)},
           "path_triggers_on_test": {"new_lessons_per_changed_file_median": round(statistics.median(p_per_file), 2)},
           "warm": {"per_file_briefings": sum(len(t["paths"]) for t in tasks.values()), "fell_back": len(fell_back),
                    "shortest_text": min(fell_back) if fell_back else None,
                    "at_the_cut": sum(1 for n in fell_back if n == ba.CUT), "retries": receipt["warm_retries"]}}
    dest = rr.REPO / "evals" / "results" / f"briefing-arms-detail-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    print(f"receipt: {dest.relative_to(rr.REPO)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
