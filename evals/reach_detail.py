#!/usr/bin/env python3
"""REPORT §4ao's reading of its misses and §4an's limits, computed after the runs, not pre-registered.

For the review: reach by where a lesson came from, by whether the change was cut and by lesson type;
the lessons missed most; what it reaches alongside the briefing arms; and whether the ledger's missed
file was inside the change the review saw. For the path triggers: how a file match could have reached
each needed lesson, what kind of entry the drafts are, and what the changes did to their files.

    python3 evals/reach_detail.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import briefing_arms as ba
import lesson_review as lr
import path_triggers as pt
import realwork_reach as rr

from okl.store import path_matches

REVIEW_RECEIPT = rr.REPO / "evals" / "results" / "lesson-review-20261108-1832.json"
LEDGER_FILE, TOP = "tests/test_intake.py", 10


def git(*args: str) -> str:
    """git's stdout in this repository."""
    return subprocess.run(["git", "-C", str(rr.REPO), *args], capture_output=True, text=True, check=True).stdout


def share(rows: list[dict], pred: Callable[..., bool]) -> dict:
    """Needed lessons flagged, among those `pred` selects."""
    pairs = [i in t["flagged"] for t in rows for i in t["needed"] if pred(t, i)]
    return {"flagged": sum(pairs), "needed": len(pairs), "share": round(sum(pairs) / max(1, len(pairs)), 3)}


def review_detail(tasks: dict[int, dict]) -> dict:
    """§4ao's misses, read."""
    rows = json.loads(REVIEW_RECEIPT.read_text())["per_task"]
    con = sqlite3.connect(rr.SNAPSHOT)
    types = dict(con.execute("select id, type from node"))
    con.close()
    arms = {x["pr"]: x["named"] for x in json.loads(lr.ARMS_RECEIPT.read_text())["per_task"]}
    trig = {x["pr"]: set(x["named"]["P"]) for x in json.loads(lr.TRIGGERS_RECEIPT.read_text())["per_task"]}
    missed = Counter(i for t in rows for i in t["missed"])
    needed = Counter(i for t in rows for i in t["needed"])
    total = sum(needed.values())

    def union(other: Callable[[int], set[str]]) -> dict:
        n = sum(1 for t in rows for i in t["needed"] if i in t["flagged"] or i in other(t["pr"]))
        return {"named": n, "of": total, "share": round(n / total, 3)}

    base = union(lambda pr: set(arms[pr]["base"]))
    base_alone = sum(1 for t in rows for i in t["needed"] if i in arms[t["pr"]]["base"])
    t388 = tasks[lr.LEDGER_PR]
    return {"by_origin": {"own": share(rows, lambda _t, i: not i.startswith("seed:")),
                          "seed_pack": share(rows, lambda _t, i: i.startswith("seed:"))},
            "by_cut": {"tasks_cut": sum(1 for t in rows if tasks[t["pr"]]["cut"]),
                       "cut": share(rows, lambda t, _i: tasks[t["pr"]]["cut"]),
                       "not_cut": share(rows, lambda t, _i: not tasks[t["pr"]]["cut"])},
            "by_type": {k: share(rows, lambda _t, i, k=k: types.get(i) == k) for k in ("Rule", "Defect", "Decision", "Gate")},
            "most_missed": [{"lesson": i, "missed": c, "needed": needed[i]} for i, c in missed.most_common(TOP)],
            "alongside": {"review_or_base": base, "base_alone": base_alone, "review_caught_base_did_not": base["named"] - base_alone,
                          "review_or_S10": union(lambda pr: set(arms[pr]["S10"])),
                          "review_or_P_and_base": union(lambda pr: trig[pr])},
            "ledger_miss": {"lesson": "seed:rag-defects:qz_fixtures", "pr": lr.LEDGER_PR, "change_chars": t388["change_chars"], "cut": t388["cut"],
                            "file": LEDGER_FILE, "file_inside_the_change_seen": LEDGER_FILE in lr.change_of(t388)}}


def path_limits(test: list[dict], boundary_commit: str) -> dict:
    """How a file match could have reached each needed lesson on the test half, and how brittle the drafts are."""
    labels = {}
    for line in rr.LABELS.read_text().splitlines():
        r = json.loads(line)
        labels[(r["pr"], r["lesson"])] = r.get("verdict")
    triggers = {}
    for line in pt.OUT.read_text().splitlines():
        r = json.loads(line)
        if r.get("prompt") == pt.PROMPT_SHA:
            triggers[r["lesson"]] = r["paths"]
    reach: Counter = Counter()
    statuses: Counter = Counter()
    for t in test:
        status = {}
        for line in git("diff", "--name-status", "-M", t["base"], t["commit"]).splitlines():
            parts = line.split("\t")
            status[parts[-1]] = parts[0][0]
        statuses.update(status.values())
        for i in t["lessons"]:
            if labels.get((t["pr"], i)) != "needed":
                continue
            entries = triggers.get(i, [])
            hit = [f for f in t["paths"] if any(path_matches(e, f) for e in entries)]
            if not entries:
                reach["no_entries_applies_anywhere"] += 1
            elif not hit:
                reach["entries_but_no_changed_file_matched"] += 1
            elif all(status.get(f) in ("A", "R") for f in hit):
                reach["matched_only_a_new_or_moved_file"] += 1
            else:
                reach["matched_a_file_that_already_existed"] += 1
    at_boundary, at_head = git("ls-tree", "-r", "--name-only", boundary_commit).splitlines(), git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    kinds: Counter = Counter()
    dead = 0
    for entries in triggers.values():
        for e in entries:
            kinds["pattern" if "*" in e else "folder" if e.endswith("/") else "exact_file"] += 1
            dead += any(path_matches(e, f) for f in at_boundary) and not any(path_matches(e, f) for f in at_head)
    return {"needed_pairs_on_test_half": dict(reach), "entries_by_kind": dict(kinds), "entries_dead_since_the_boundary": dead,
            "changed_files_on_test_half_by_status": dict(statuses)}


def main() -> int:
    """Write the detail receipt."""
    all_tasks = [json.loads(line) for line in rr.TASKS.read_text().splitlines() if line.strip()]
    dev, test = ba.halves(all_tasks)
    out = {"section": "4ao misses and 4an limits, not pre-registered", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "okl_commit": git("rev-parse", "HEAD").strip(), "status": "model-judged, not yet audited (#394)",
           "review": review_detail({t["pr"]: t for t in all_tasks}), "path_triggers": path_limits(test, dev[-1]["commit"])}
    dest = rr.REPO / "evals" / "results" / f"reach-detail-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    print(f"receipt: {dest.relative_to(rr.REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
