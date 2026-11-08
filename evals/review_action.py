#!/usr/bin/env python3
"""REPORT §4ap: a review that says whether a change followed each lesson, on the first 25 tasks.

`key` builds the answer key with Opus before any review exists for these tasks. `run` asks Sonnet about
every lesson against the whole change, read in parts, and refuses until the key is complete. `run --pilot`
makes one call on a task outside this test, to check the plumbing, and keeps nothing. `score` reads the
answers against the key and writes the receipt. Answers land in evals/bench/private/realwork/ as each
call returns, so a rerun asks only for what is missing.

    python3 evals/review_action.py key
    python3 evals/review_action.py run [--pilot]
    python3 evals/review_action.py score [--receipt]
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import random
import re
import statistics
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import lesson_review as lr
import realwork_label as rl
import realwork_reach as rr
import review_state_detail as rsd

WHOLE_LABELS = lr.PRIVATE / "whole-change-labels.jsonl"
KEY = lr.PRIVATE / "action-key.jsonl"
ANSWERS = lr.PRIVATE / "action-review-answers.jsonl"
USAGE = lr.PRIVATE / "action-review-usage.jsonl"
WORDS, RAISED = ("none", "done", "ask", "gap"), ("ask", "gap")   # WORDS runs from least to most for the author to do
LEDGER_PR, WORKERS = lr.LEDGER_PR, 3
REACH_BAR, WRONG_BAR, RAISED_BAR = 0.70, 5, 10
REACH_4AO_SORTED, FLAGGED_4AO, FOLLOWED_FLAGGED_4AO = 0.816, 12, 0.455   # §4ao and its sort, for the predictions

PROMPT = """You are reviewing a pull request against what a team has learned the hard way and written down so it is not repeated.

PULL REQUEST: {title}

WHAT IT WAS FOR:
{issues}

FILES THE WHOLE PULL REQUEST CHANGES:
{files}

THE DIFF (part {part} of {parts}):
{change}

WHAT THE TEAM HAS WRITTEN DOWN:
{lessons}

For each item above, decide which one word is true of this part of the change:
- "none": this part does nothing the item is about. Most items are this. An item on a similar subject that changes nothing here is "none". If the item would be met by a file listed above that this part does not show, it is "none".
- "done": this part does something the item is about, and does it the way the item asks, or avoids what it warns of. The author has no work here.
- "gap": this part does what the item warns against, or leaves out what the item asks for. Something left out counts, and it has no line of its own.
- "ask": the item applies, but whether it is met depends on something the change does not show, so the author has to confirm it before merging.

An item can apply without sharing a word with the diff.

Reply with one JSON array and nothing else, holding one object for every item, each exactly once: [{{"id": "<the id in square brackets>", "reason": "<what in the change led you to the word; empty for none>", "answer": "none|done|gap|ask", "to_author": "<for gap or ask, one sentence telling the author what to do; otherwise empty>"}}]"""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
_lock = threading.Lock()


@functools.cache
def _diff(base: str, commit: str) -> str:
    return rl.git("diff", f"{base}..{commit}")


def whole(task: dict) -> str:
    """The task's whole change, uncut."""
    return _diff(task["base"], task["commit"])


def parts_of(diff: str, limit: int = rl.CUT) -> list[str]:
    """`diff` in pieces of at most `limit` characters, cut between files, or between lines inside a longer file."""
    parts, current = [], ""
    for block in (b for b in re.split(r"(?m)^(?=diff --git )", diff) if b):
        if current and len(block) <= limit < len(current) + len(block):   # a file that fits a part of its own starts one
            parts.append(current)
            current = ""
        rest = current + block
        while len(rest) > limit:
            end = rest.rfind("\n", 1, limit) + 1 or limit
            parts.append(rest[:end])
            rest = rest[end:]
        current = rest
    if current:
        parts.append(current)
    if "".join(parts) != diff:
        raise ValueError("the parts do not rebuild the diff")
    return parts


def relabel(tasks: list[dict], texts: dict[str, str]) -> dict[tuple[int, str], dict]:
    """Label every lesson against the whole change on `tasks`, with §4al's judge and prompt."""
    done = {k: r for k, r in rsd.load(WHOLE_LABELS).items() if r.get("verdict")}
    with tempfile.TemporaryDirectory(prefix="okl-4ap-") as tmp, WHOLE_LABELS.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        room = Path(tmp)
        for attempt in range(lr.ROUNDS):
            jobs = []
            for t in tasks:
                todo = [i for i in sorted(t["lessons"]) if (t["pr"], i) not in done and i in texts]
                jobs += [(t, todo[k:k + rl.BATCH]) for k in range(0, len(todo), rl.BATCH)]
            if not jobs:
                break
            print(f"labels, round {attempt + 1}: {len(jobs)} calls", file=sys.stderr, flush=True)
            for future in as_completed([pool.submit(rl.label_batch, t, ids, texts, whole(t), room) for t, ids in jobs]):
                for r in future.result():
                    if r.get("verdict"):
                        done[(r["pr"], r["lesson"])] = r
                        sink.write(json.dumps(r, ensure_ascii=False) + "\n")
                sink.flush()
    return done


def labels_for(tasks: list[dict], texts: dict[str, str]) -> dict[tuple[int, str], dict]:
    """Each pair's first reading: §4al's, or the whole-change label on a task §4al's judge saw only the start of."""
    first = rsd.load(rr.LABELS)
    again = rsd.load(WHOLE_LABELS)
    return {(t["pr"], i): (again if len(whole(t)) > rl.CUT else first).get((t["pr"], i), {})
            for t in tasks for i in t["lessons"] if i in texts}


def needed_of(labels: dict[tuple[int, str], dict]) -> dict[tuple[int, str], str]:
    """The pairs labelled needed, with the evidence the label rests on."""
    return {k: r.get("evidence") or "" for k, r in labels.items() if r.get("verdict") == "needed"}


def key_gaps(tasks: list[dict], texts: dict[str, str]) -> list[str]:
    """What the answer key still lacks: an unlabelled pair, or a needed pair not sorted."""
    labels = labels_for(tasks, texts)
    sorted_pairs = rsd.load(KEY)
    gaps = [f"#{pr} {i}: no label" for (pr, i), r in labels.items() if not r.get("verdict")]
    return gaps + [f"#{pr} {i}: not sorted" for (pr, i) in needed_of(labels) if (pr, i) not in sorted_pairs]


def make_key() -> int:
    """Build the answer key: labels on the changes §4al cut, then the state of every needed pair."""
    dev, _ = lr.load_tasks()
    texts = rl.lesson_text(rr.SNAPSHOT)
    relabel([t for t in dev if len(whole(t)) > rl.CUT], texts)
    labels = labels_for(dev, texts)
    needed = needed_of(labels)
    states = rsd.sort_pairs(dev, needed, whole, KEY)
    gaps = key_gaps(dev, texts)
    print(json.dumps({"pairs": len(labels), "needed": len(needed), "states": Counter(states[k]["state"] for k in needed if k in states), "gaps": gaps[:20]}))
    return 0 if not gaps else 2


def one(job: dict, texts: dict[str, str], room: Path) -> tuple[list[dict], dict]:
    """One call: the answers it gave for this job's lessons on this part, and its cost."""
    t = job["task"]
    issues = "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in t["issues"]) or "(none)"
    prompt = PROMPT.format(title=t["title"], issues=issues, files="\n".join(t["paths"]), part=job["part"] + 1, parts=job["parts"],
                           change=job["text"], lessons="\n\n".join(texts[i] for i in job["ids"]))
    got, use = lr.ask(prompt, room)
    wanted, rows = set(job["ids"]), []
    for item in got or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item.get("answer") not in WORDS:
            continue
        lesson = lr.resolve(item["id"], job["ids"])
        if lesson in wanted:
            wanted.discard(lesson)
            rows.append({"pr": t["pr"], "part": job["part"], "lesson": lesson, "answer": item["answer"],
                         "to_author": str(item.get("to_author") or "")[:lr.LINE_CUT], "model": lr.MODEL, "prompt": PROMPT_SHA})
    return rows, {"pr": t["pr"], "part": job["part"], "asked": len(job["ids"]), "answered": len(rows), "prompt": PROMPT_SHA, **use}


def load_answers() -> dict[tuple[int, int, str], dict]:
    """The answers kept so far under this prompt."""
    rows = [json.loads(line) for line in ANSWERS.read_text().splitlines()] if ANSWERS.exists() else []
    return {(r["pr"], r["part"], r["lesson"]): r for r in rows if r.get("prompt") == PROMPT_SHA}


def jobs_for(tasks: list[dict], texts: dict[str, str], done: dict[tuple[int, int, str], dict]) -> list[dict]:
    """Every call still to make: each part of each task, twenty unanswered lessons a call."""
    jobs = []
    for t in tasks:
        parts = parts_of(whole(t))
        for p, text in enumerate(parts):
            todo = [i for i in sorted(t["lessons"]) if (t["pr"], p, i) not in done and i in texts]
            jobs += [{"task": t, "part": p, "parts": len(parts), "text": text, "ids": todo[k:k + rl.BATCH]} for k in range(0, len(todo), rl.BATCH)]
    return jobs


def run(pilot: bool) -> int:
    """Ask for every pair not yet answered (or make the pilot's one call)."""
    dev, test = lr.load_tasks()
    texts = rl.lesson_text(rr.SNAPSHOT)
    with tempfile.TemporaryDirectory(prefix="okl-4ap-") as tmp:
        room = Path(tmp)   # the reviewer runs outside the repository, with no tools
        if pilot:
            t = next(x for x in test if x["pr"] != LEDGER_PR)   # a task §4ao already read, outside this test
            job = jobs_for([t], texts, {})[0]
            rows, use = one(job, texts, room)
            print(json.dumps({"pilot_on": t["pr"], "cost": use, "answers": Counter(r["answer"] for r in rows)}, indent=1))
            return 0 if use["answered"] == use["asked"] else 2
        gaps = key_gaps(dev, texts)
        if gaps:
            sys.exit(f"the answer key is not complete, so no review runs: {len(gaps)} gaps, first {gaps[0]}")
        tasks = [*dev, next(x for x in test if x["pr"] == LEDGER_PR)]
        done = load_answers()
        with ANSWERS.open("a") as answers, USAGE.open("a") as usage, ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for attempt in range(lr.ROUNDS):
                jobs = jobs_for(tasks, texts, done)
                if not jobs:
                    break
                print(f"round {attempt + 1}: {len(jobs)} calls · {lr.MODEL} prompt {PROMPT_SHA}", file=sys.stderr, flush=True)
                for n, future in enumerate(as_completed([pool.submit(one, j, texts, room) for j in jobs]), 1):
                    rows, use = future.result()
                    with _lock:
                        for r in rows:
                            done[(r["pr"], r["part"], r["lesson"])] = r
                            answers.write(json.dumps(r, ensure_ascii=False) + "\n")
                        usage.write(json.dumps(use) + "\n")
                        answers.flush()
                        usage.flush()
                    if n % 25 == 0:
                        print(f"  {n}/{len(jobs)} calls", file=sys.stderr, flush=True)
        missing = len(jobs_for(tasks, texts, done))
    print(json.dumps({"tasks": len(tasks), "answered": len(done), "calls_still_missing": missing, "prompt": PROMPT_SHA}))
    return 0 if not missing else 2


def verdict_of(answers: dict[tuple[int, int, str], dict], task: dict, lesson: str) -> str:
    """The lesson's answer on the whole change: the one asking most of the author, across its parts."""
    got = [answers[(task["pr"], p, lesson)]["answer"] for p in range(len(parts_of(whole(task)))) if (task["pr"], p, lesson) in answers]
    return max(got, key=WORDS.index, default="none")


def task_row(task: dict, labels: dict[tuple[int, str], dict], key: dict[tuple[int, str], dict], answers: dict[tuple[int, int, str], dict]) -> dict:
    """One task's scoring row, in the shape briefing_arms.tally reads."""
    pr = task["pr"]
    ids = sorted(i for i in task["lessons"] if (pr, i) in labels)
    word = {i: verdict_of(answers, task, i) for i in ids}
    verdict = {i: labels[(pr, i)].get("verdict") for i in ids}
    state = {i: key[(pr, i)]["state"] for i in ids if verdict[i] == "needed" and (pr, i) in key}
    raised = sorted(i for i in ids if word[i] in RAISED)
    action = sorted(i for i, s in state.items() if s in rsd.ACTION)
    wrong = sorted(i for i in raised if verdict[i] == "no" or state.get(i) == "followed")
    return {"pr": pr, "needed": action, "named": {"base": [], "review": raised}, "wrong": wrong, "confirmed": sorted(set(raised) & set(action)),
            "unresolved": sorted(set(raised) - set(wrong) - set(action)), "missed": sorted(set(action) - set(raised)),
            "words": {i: word[i] for i in state}, "states": state}


def cost_of() -> dict:
    """Calls, tokens, model seconds and API-priced dollars, per pull request."""
    use = [json.loads(line) for line in USAGE.read_text().splitlines()] if USAGE.exists() else []
    use = [u for u in use if u.get("prompt") == PROMPT_SHA]
    by_pr: dict[int, dict] = {}
    for u in use:
        p = by_pr.setdefault(u["pr"], {"calls": 0, "tokens": 0, "seconds": 0.0, "usd": 0.0})
        p["calls"] += 1
        p["tokens"] += u.get("input", 0) + u.get("cache_read", 0) + u.get("cache_write", 0) + u.get("output", 0)
        p["seconds"] += u.get("seconds", 0)
        p["usd"] += u.get("api_priced_usd", 0) or 0
    out = {"calls": len(use), "unanswered_calls": sum(1 for u in use if u.get("answered", 0) < u.get("asked", 0))}
    if by_pr:
        out |= {f"per_pr_median_{k}": round(statistics.median(p[k] for p in by_pr.values()), 2) for k in ("calls", "tokens", "seconds", "usd")}
        out["total_api_priced_usd"] = round(sum(p["usd"] for p in by_pr.values()), 2)
    return out


def score(write: bool) -> int:
    """Score the answers against the key; write the receipt with `write`."""
    dev, test = lr.load_tasks()
    texts = rl.lesson_text(rr.SNAPSHOT)
    on_388 = next(t for t in test if t["pr"] == LEDGER_PR)
    labels, key, answers = labels_for(dev, texts), rsd.load(KEY), load_answers()
    missing = sum(len(j["ids"]) for j in jobs_for([*dev, on_388], texts, answers))
    gaps = key_gaps(dev, texts)
    rows = [task_row(t, labels, key, answers) for t in dev]
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    v = ba.tally(rows, "review", {}, rng)   # with an empty base, the gain is the reach and its interval the reach's
    raised, wrong = [len(r["named"]["review"]) for r in rows], [len(r["wrong"]) for r in rows]
    followed = [(i, r) for r in rows for i, s in r["states"].items() if s == "followed"]
    followed_raised = sum(1 for i, r in followed if r["words"][i] in RAISED)
    grid = Counter(f"{s} -> {r['words'][i]}" for r in rows for i, s in r["states"].items())
    ledger = [json.loads(line)["lesson"] for line in lr.LEDGER.read_text().splitlines() if line.strip()]
    ledger_raised = {i: verdict_of(answers, on_388, i) in RAISED for i in ledger}
    lower, followed_share = v["gain_boot95"][0], round(followed_raised / max(1, len(followed)), 3)
    holds = {"reach_lower_bound_at_least_70": lower >= REACH_BAR, "wrong_median_at_most_5": statistics.median(wrong) <= WRONG_BAR,
             "raised_median_at_most_10": statistics.median(raised) <= RAISED_BAR, "both_ledger_lessons_raised": all(ledger_raised.values())}
    predictions = {"reach at least 81.6%, as §4ao's sort read": v["reach"] >= REACH_4AO_SORTED,
                   "raises fewer than §4ao's 12 at the median": statistics.median(raised) < FLAGGED_4AO,
                   "raises under 45.5% of the lessons the change followed": followed_share < FOLLOWED_FLAGGED_4AO,
                   "misses a lesson calling for action on more than a third of the tasks": v["failure_rate"] > 1 / 3}
    usable = not missing and not gaps
    out = {"section": "4ap", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": rl.git("rev-parse", "HEAD").strip(),
           "status": "model-judged, not yet audited (#394)" if usable else f"INCOMPLETE: {missing} answer(s) and {len(gaps)} key gap(s)", "usable": usable,
           "reviewer": {"model": lr.MODEL, "prompt": PROMPT_SHA}, "key": {"labels_prompt": rl.PROMPT_SHA, "sort_model": "opus", "sort_prompt": rsd.PROMPT_SHA},
           "inputs": {"labels_sha256": ba.sha256(rr.LABELS), "tasks_sha256": ba.sha256(rr.TASKS), "store_sha256": ba.sha256(rr.SNAPSHOT),
                      "whole_labels_sha256": ba.sha256(WHOLE_LABELS), "key_sha256": ba.sha256(KEY)},
           "result": {"tasks": v["tasks"], "tasks_with_action": v["tasks_with_needed"], "calling_for_action": v["needed"], "reach": v["reach"], "reach_boot95": v["gain_boot95"],
                      "tasks_missing": v["tasks_missing"], "failure_rate": v["failure_rate"], "failure_wilson95": v["failure_wilson95"],
                      "raised_median": statistics.median(raised), "raised_max": max(raised), "wrong_median": statistics.median(wrong), "wrong_max": max(wrong),
                      "confirmed_total": sum(len(r["confirmed"]) for r in rows), "wrong_total": sum(wrong), "unresolved_total": sum(len(r["unresolved"]) for r in rows),
                      "followed": len(followed), "followed_raised": followed_raised, "followed_raised_share": followed_share},
           "key_state_to_word": dict(sorted(grid.items())), "ledger_on_388": ledger_raised, "cost": cost_of(), "holds": {**holds, "all": all(holds.values())},
           "predictions": predictions, "per_task": rows}
    print(out["status"])
    print(json.dumps({k: out[k] for k in ("result", "key_state_to_word", "ledger_on_388", "cost", "holds", "predictions")}, indent=1))
    if write:
        path = rr.REPO / "evals" / "results" / f"review-action-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(rr.REPO)}")
    return 0 if usable else 2


def main() -> int:
    """Dispatch `key`, `run` or `score`."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("key")
    sub.add_parser("run").add_argument("--pilot", action="store_true")
    sub.add_parser("score").add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    if args.cmd == "key":
        return make_key()
    return run(args.pilot) if args.cmd == "run" else score(args.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
