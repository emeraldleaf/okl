#!/usr/bin/env python3
"""Were the lessons a briefing actually showed during real work followed more often than the ones it did not show?

Exploratory and observational, not pre-registered. It calls no model: it joins the store's
exposure log (which lessons each briefing showed, and when) with the answer keys of §4al and
§4aq (which lessons each real pull request needed, and whether the change followed each).

The method, fixed before the data was read (2026-11-10):
- Tasks: §4al's 50 (states from §4ap's key for half of them and §4ao's sort for the other half;
  each key holds only the pairs it judged needed) and §4aq's 50 (labels and states in the private
  4aq files). Corrected 2026-11-10: the first run read only §4ap's key, so half of §4al's tasks. A pair counts when its label is needed and
  its state is followed or not followed; check and unclear are left out.
- Window: from WINDOW_HOURS before the earliest commit in base..commit to that commit's time.
  The sensitivity run widens the start to SENSITIVITY_HOURS.
- Shown: every lesson in a briefing logged for repo okl inside the window. Read only.
- Tasks whose window starts before the log's first entry have no exposure data and are left out.
- Measures: the follow rate among shown and among not-shown pairs, and their difference, with a
  bootstrap over tasks (2000 resamples, seed 4); and, among lessons both shown and not shown on
  different tasks, how many were followed more often when shown, with the pair-weighted
  difference within lessons.

Shown means shown in full: the log does not record the lessons a briefing named in one line.

Limits: it is a correlation. A lesson the task's words matched may be easier to follow anyway,
and a session on another branch in the same window counts as shown. The labels are model-judged
and not yet audited (#394).

    python3 evals/briefed_follow.py
"""
from __future__ import annotations

import json
import random
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_action as ra
import review_repo as rp
import review_state_detail as rsd

REPO = Path(__file__).resolve().parents[1]
WINDOW_HOURS, SENSITIVITY_HOURS = 2, 6
BOOT, SEED = 2000, 4


def commit_times(base: str, commit: str) -> tuple[int, int]:
    """The earliest commit time in base..commit, and the commit's own, in seconds."""
    times = [int(t) for t in subprocess.run(["git", "-C", str(REPO), "log", "--format=%ct", f"{base}..{commit}"],
                                            capture_output=True, text=True, check=True).stdout.split()]
    own = int(subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%ct", commit],
                             capture_output=True, text=True, check=True).stdout)
    return (min(times) if times else own), own


def briefings() -> list[tuple[int, set[str]]]:
    """Every briefing logged for okl: when (seconds) and which lessons it showed."""
    con = sqlite3.connect(f"file:{REPO / '.okl' / 'okl.db'}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT at, node_ids FROM briefing WHERE repo = 'okl'").fetchall()
    finally:
        con.close()
    out = []
    for at, ids in rows:
        parsed = json.loads(ids) if ids and ids.startswith("[") else [i for i in (ids or "").split(",") if i]
        out.append((int(at) // 1000, set(parsed)))
    return sorted(out, key=lambda r: r[0])


def pairs() -> list[dict]:
    """Every needed pair whose change followed or did not follow its lesson, with its task."""
    out = []
    # Two keys sorted §4al's tasks: §4ap's (action-key) half and §4ao's sort the other half.
    al_states = {**rsd.load(rsd.ANSWERS), **rsd.load(ra.KEY)}
    for t in map(json.loads, (REPO / "evals" / "realwork" / "tasks.jsonl").read_text().splitlines()):
        for i in t["lessons"]:
            state = al_states.get((t["pr"], i), {}).get("state")   # a key holds only pairs it judged needed
            if state in ("followed", "not_followed"):
                out.append({"set": "4al", "task": t, "lesson": i, "followed": state == "followed"})
    aq_labels, aq_states = rp.keyed(rp.LABELS), rp.keyed(rp.STATES)
    for t in rp.load_tasks():
        for i in t["lessons"]:
            state = aq_states.get((t["pr"], i), {}).get("state")
            if aq_labels.get((t["pr"], i), {}).get("verdict") == "needed" and state in ("followed", "not_followed"):
                out.append({"set": "4aq", "task": t, "lesson": i, "followed": state == "followed"})
    return out


def rate(rows: list[dict]) -> float | None:
    """The share of `rows` whose change followed its lesson, or None for none."""
    return round(sum(r["followed"] for r in rows) / len(rows), 3) if rows else None


def measure(rows: list[dict], log: list[tuple[int, set[str]]], hours: int) -> dict:
    """Shown or not for each pair in its window, the two follow rates and their difference."""
    first_logged = log[0][0]
    windows: dict[tuple[str, int], tuple[int, int] | None] = {}
    kept = []
    for r in rows:
        key = (r["set"], r["task"]["pr"])
        if key not in windows:
            start, end = commit_times(r["task"]["base"], r["task"]["commit"])
            windows[key] = None if start - hours * 3600 < first_logged else (start - hours * 3600, end)
        w = windows[key]
        if w is None:
            continue
        shown = any(w[0] <= at <= w[1] and r["lesson"] in ids for at, ids in log)
        kept.append({**r, "shown": shown, "key": key})
    shown, unseen = [r for r in kept if r["shown"]], [r for r in kept if not r["shown"]]
    by_task: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in kept:
        by_task[r["key"]].append(r)
    tasks = list(by_task)
    rng, diffs = random.Random(SEED), []   # noqa: S311 - a seeded bootstrap, not a secret
    for _ in range(BOOT):
        sample = [r for k in (tasks[rng.randrange(len(tasks))] for _ in tasks) for r in by_task[k]]
        a, b = rate([r for r in sample if r["shown"]]), rate([r for r in sample if not r["shown"]])
        if a is not None and b is not None:
            diffs.append(a - b)
    diffs.sort()
    by_lesson: dict[str, list[dict]] = defaultdict(list)
    for r in kept:
        by_lesson[r["lesson"]].append(r)
    both = {i: rs for i, rs in by_lesson.items() if any(r["shown"] for r in rs) and any(not r["shown"] for r in rs)}
    within = [(rate([r for r in rs if r["shown"]]) or 0) - (rate([r for r in rs if not r["shown"]]) or 0) for rs in both.values()]
    weights = [len(rs) for rs in both.values()]
    return {"window_hours_before_first_commit": hours, "tasks_with_exposure_data": len(tasks),
            "tasks_left_out_before_the_log": len({k for k, w in windows.items() if w is None}),
            "pairs": len(kept), "shown": {"pairs": len(shown), "followed_rate": rate(shown)},
            "not_shown": {"pairs": len(unseen), "followed_rate": rate(unseen)},
            "difference": round((rate(shown) or 0) - (rate(unseen) or 0), 3) if shown and unseen else None,
            "difference_boot95": [round(diffs[int(0.025 * len(diffs))], 3), round(diffs[int(0.975 * len(diffs)) - 1], 3)] if diffs else None,
            "within_lessons": {"lessons_both_shown_and_not": len(both),
                               "followed_more_when_shown": sum(1 for d in within if d > 0),
                               "followed_less_when_shown": sum(1 for d in within if d < 0), "same": sum(1 for d in within if d == 0),
                               "pair_weighted_difference": round(sum(d * w for d, w in zip(within, weights, strict=True)) / sum(weights), 3) if weights else None}}


def main() -> int:
    """Write the receipt and print it."""
    log, rows = briefings(), pairs()
    out = {"section": "briefed lessons followed on real work: exploratory, observational, not pre-registered",
           "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "okl_commit": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "status": "model-judged labels, not yet audited (#394); a correlation, not an effect",
           "log": {"briefings": len(log), "first": datetime.fromtimestamp(log[0][0], UTC).strftime("%Y-%m-%d"),
                   "last": datetime.fromtimestamp(log[-1][0], UTC).strftime("%Y-%m-%d")},
           "main": measure(rows, log, WINDOW_HOURS), "sensitivity": measure(rows, log, SENSITIVITY_HOURS)}
    dest = REPO / "evals" / "results" / f"briefed-follow-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    print(f"receipt: {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
