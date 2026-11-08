#!/usr/bin/env python3
"""REPORT §4ao's misses by the state of the change: sorted after the run, not pre-registered.

§4al's label asks what a change needed when it was written, which suits a briefing. A review arrives
afterwards and has work only where the change as written has not followed the lesson. `sort` has Opus,
shown nothing of the review's answers, put each needed pair on §4ao's tasks in one state; `score` reads
the review's flags within each state.

    python3 evals/review_state_detail.py sort
    python3 evals/review_state_detail.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import lesson_review as lr
import realwork_label as rl
import realwork_reach as rr

ANSWERS = lr.PRIVATE / "review-states-4ao.jsonl"
SORTER = ["claude", "-p", "--model", "opus", "--restricted", "--strict-mcp-config", "--output-format", "json",
          "--tools", ""]
STATES, ACTION = ("followed", "not_followed", "check", "unclear"), ("not_followed", "check")
SORT_TIMEOUT, WHY_CUT, WORKERS = 900, 240, 3
PROMPT = """A team keeps lessons: rules, past defects and decisions it learned. Below is a pull request's change as written, and some lessons that were judged relevant to it. Each lesson comes with the part of the change the earlier reader said it rests on.

For each lesson, say what state the change as written is in:
- "followed": the change already does what the lesson asks, or already avoids what it warns of. A reviewer who knew the lesson would have nothing to ask for because of it.
- "not_followed": the change does what the lesson warns against, or leaves out something the lesson asks for. A reviewer who knew the lesson would ask for a change.
- "check": the diff alone cannot settle it. It depends on something outside the diff, so a reviewer who knew the lesson would ask the author to check it before merging.
- "unclear": you cannot tell, or you do not think this lesson bears on the change.

TITLE: {title}

ISSUE:
{issues}

CHANGE:
{change}

LESSONS:
{lessons}

Answer with one JSON array and nothing else, one object per lesson, every lesson exactly once: [{{"id": "<lesson id>", "state": "followed|not_followed|check|unclear", "why": "<one short sentence>"}}]"""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]


def load(path: Path) -> dict[tuple[int, str], dict]:
    """The sorted pairs kept in `path`."""
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return {(r["pr"], r["lesson"]): r for r in rows}


def needed_evidence() -> dict[tuple[int, str], str]:
    """Each pair §4al labelled needed, with the part of the change the judge said it rests on."""
    rows = [json.loads(line) for line in rr.LABELS.read_text().splitlines()]
    return {(r["pr"], r["lesson"]): r.get("evidence") or "" for r in rows if r.get("verdict") == "needed"}


def ask(prompt: str, room: str) -> list:
    """The sorter's array for `prompt`, or nothing when it gave none (a later round asks again)."""
    try:
        p = subprocess.run(SORTER, input=prompt, capture_output=True, text=True, timeout=SORT_TIMEOUT, cwd=room)
    except subprocess.TimeoutExpired:
        return []
    try:
        return rl.last_array(json.loads(p.stdout).get("result") or "") or []
    except ValueError:
        return rl.last_array(p.stdout) or []


def sort_batch(task: dict, ids: list[str], evidence: dict[tuple[int, str], str], texts: dict[str, str],
               *, change: str, room: str) -> list[dict]:
    """One call: the states it gave for `ids`."""
    issues = "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in task["issues"]) or "(none)"
    lessons = "\n\n".join(f"{texts[i]}\nTHE PART OF THE CHANGE IT RESTS ON: {evidence[(task['pr'], i)] or '(none given)'}" for i in ids)
    out = []
    for item in ask(PROMPT.format(title=task["title"], issues=issues, change=change, lessons=lessons), room):
        if isinstance(item, dict) and item.get("state") in STATES and isinstance(item.get("id"), str):
            lesson = lr.resolve(item["id"], ids)
            if lesson:
                out.append({"pr": task["pr"], "lesson": lesson, "state": item["state"], "why": str(item.get("why", ""))[:WHY_CUT]})
    return out


def sort_pairs(tasks: list[dict], evidence: dict[tuple[int, str], str], change_of: Callable[[dict], str], out: Path) -> dict[tuple[int, str], dict]:
    """Sort every pair of `evidence` on `tasks` not yet in `out`, twenty a call, order shuffled."""
    texts = rl.lesson_text(rr.SNAPSHOT)
    done = load(out)
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded shuffle, not a secret
    changes = {t["pr"]: change_of(t) for t in tasks}
    with tempfile.TemporaryDirectory(prefix="okl-state-") as room, out.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for attempt in range(lr.ROUNDS):
            jobs = []
            for t in tasks:
                todo = [i for i in sorted(t["lessons"]) if (t["pr"], i) in evidence and (t["pr"], i) not in done and i in texts]
                rng.shuffle(todo)
                jobs += [(t, todo[k:k + rl.BATCH]) for k in range(0, len(todo), rl.BATCH)]
            if not jobs:
                break
            print(f"round {attempt + 1}: {len(jobs)} calls · prompt {PROMPT_SHA}", file=sys.stderr, flush=True)
            futures = [pool.submit(sort_batch, t, ids, evidence, texts, change=changes[t["pr"]], room=room) for t, ids in jobs]
            for future in as_completed(futures):
                for r in future.result():
                    done[(r["pr"], r["lesson"])] = r
                    sink.write(json.dumps(r, ensure_ascii=False) + "\n")
                sink.flush()
    return done


def share(group: list[dict]) -> dict:
    """How many of `group` the review flagged."""
    n = sum(p["flagged"] for p in group)
    return {"flagged": n, "of": len(group), "share": round(n / max(1, len(group)), 3)}


def score(write: bool) -> int:
    """Read the review's flags within each state; write the receipt with `write`."""
    _, test = lr.load_tasks()
    evidence, flags, states = needed_evidence(), lr.load_answers(), load(ANSWERS)
    pairs = [{"pr": t["pr"], "lesson": i, "state": states[(t["pr"], i)]["state"], "flagged": flags[(t["pr"], i)]["flag"],
              "origin": "seed_pack" if i.startswith("seed:") else "own"}
             for t in test for i in sorted(t["lessons"]) if (t["pr"], i) in evidence]
    calls_for_action = [p for p in pairs if p["state"] in ACTION]
    followed = [p for p in pairs if p["state"] == "followed"]
    rows = [{"pr": t["pr"], "needed": [p["lesson"] for p in calls_for_action if p["pr"] == t["pr"]],
             "named": {"base": [], "review": sorted(i for i in t["lessons"] if flags[(t["pr"], i)]["flag"])}} for t in test]
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    v = ba.tally(rows, "review", {}, rng)   # with an empty base, the gain is the reach and its interval the reach's
    flagged_action = [len(set(r["needed"]) & set(r["named"]["review"])) for r in rows]
    flagged_followed = [sum(p["flagged"] for p in followed if p["pr"] == r["pr"]) for r in rows]
    missed = [{"pr": p["pr"], "lesson": p["lesson"], "state": p["state"], "why": states[(p["pr"], p["lesson"])]["why"]}
              for p in calls_for_action if not p["flagged"]]
    out = {"section": "4ao by state, not pre-registered", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "okl_commit": rl.git("rev-parse", "HEAD").strip(),
           "status": "model-judged, not audited (#394); sorted after the failure was known, by the judge's model",
           "sorter": {"model": "opus", "prompt": PROMPT_SHA, "saw_the_review": False},
           "note": "the sort ran from a scratch copy of this file before it was committed; the prompt is unchanged",
           "inputs": {"labels_sha256": ba.sha256(rr.LABELS), "tasks_sha256": ba.sha256(rr.TASKS), "states_sha256": ba.sha256(ANSWERS)},
           "needed": len(pairs), "flagged": sum(p["flagged"] for p in pairs),
           "by_state": {s: share([p for p in pairs if p["state"] == s]) for s in STATES},
           "calling_for_action": {"flagged": v["needed"] - sum(1 for p in calls_for_action if not p["flagged"]), "of": v["needed"], "reach": v["reach"],
                                  "reach_boot95": v["gain_boot95"], "tasks_with_one": v["tasks_with_needed"], "tasks_missing_one": v["tasks_missing"]},
           "by_origin": {o: {"followed": share([p for p in followed if p["origin"] == o]), "calling_for_action": share([p for p in calls_for_action if p["origin"] == o])}
                         for o in ("own", "seed_pack")},
           "per_pr_median": {"flagged": statistics.median(len(r["named"]["review"]) for r in rows), "flagged_calling_for_action": statistics.median(flagged_action),
                             "flagged_already_followed": statistics.median(flagged_followed)},
           "missed_calling_for_action": missed, "per_pair": pairs}
    print(json.dumps({k: v for k, v in out.items() if k != "per_pair"}, indent=1))
    if write:
        path = rr.REPO / "evals" / "results" / f"review-state-detail-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(rr.REPO)}")
    return 0


def main() -> int:
    """Dispatch `sort` or `score`."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sort")
    sub.add_parser("score").add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    if args.cmd == "score":
        return score(args.receipt)
    _, test = lr.load_tasks()
    sort_pairs(test, needed_evidence(), lr.change_of, ANSWERS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
