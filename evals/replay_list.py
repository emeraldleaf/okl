#!/usr/bin/env python3
"""REPORT §4ax: a lesson changed the code when it stood alone and was named. Does it among ten others?

§4aw's five tasks, in a two-by-two: the lesson alone or among the nine others the search ranks
highest for the task's words, and told it bears on this change or not. Graded inside each session
by §4aw's behaviour graders.

    python3 evals/replay_list.py run
    python3 evals/replay_list.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_regrade as regrade
import outcome_replay as o
import run_guard

LISTS = o.REPO / "evals" / "replay-lists-4ax.json"
OUT = o.REPO / "evals" / "bench" / "private" / "realwork" / "outcome-list-4ax.jsonl"
ARMS = ("alone_told", "alone_plain", "ten_told", "ten_plain")
HOLDS_WITHIN, MIN_COMPLETE = 0.15, 90
WRAP = {"alone_told": "This team keeps the lesson below, and it bears on this change.",
        "alone_plain": "This team keeps the lesson below.",
        "ten_told": "This team keeps the lessons below, and they bear on this change.",
        "ten_plain": "This team keeps the lessons below."}
WRAP_SHA = hashlib.sha256(json.dumps(WRAP, sort_keys=True).encode()).hexdigest()[:16]


def position(pr: int, rep: int) -> int:
    """Where the right lesson sits among the ten: seeded per session, so no task always has it first."""
    return random.Random(f"{pr}-{rep}").randrange(10)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose


def told(task: dict, arm: str, rep: int) -> str:
    """The lesson section an arm is given."""
    target = task["lesson_text"].strip()
    if arm.startswith("alone"):
        return f"\n{WRAP[arm]}\n\n<lesson>\n{target}\n</lesson>\n"
    texts = [x["text"].strip() for x in json.loads(LISTS.read_text())[str(task["pr"])]["others"]]
    texts.insert(position(task["pr"], rep), target)
    body = "\n\n".join(f"<lesson>\n{t}\n</lesson>" for t in texts)
    return f"\n{WRAP[arm]}\n\n<lessons>\n{body}\n</lessons>\n"


def calls() -> list[dict]:
    """Every session, in a seeded order, so stopping early does not favour an arm."""
    out = [{"pr": t["pr"], "arm": a, "rep": r} for t in o.tasks() for a in ARMS for r in range(o.REPEATS)]
    random.Random(o.SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def kept() -> dict[tuple, dict]:
    """Every session kept under these words and these lists."""
    if not OUT.exists():
        return {}
    want = (WRAP_SHA, o.sha(LISTS))
    return {o.ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if (r.get("wrap"), r.get("lists")) == want}


def session(call: dict, task: dict, before: set[str]) -> dict | None:
    """One agent session, then the behaviour grader on the tree it left."""
    start = time.monotonic()
    name = f"#{call['pr']} {call['arm']}{call['rep']}"
    with o.room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(o.git("diff", task["base"], task["frozen"]))
        prompt = o.PROMPT.format(task=o.task_words(task), lesson=told(task, call["arm"], call["rep"]))
        try:
            p = subprocess.run(o.AGENT, input=prompt, capture_output=True, text=True, timeout=o.TIMEOUT, cwd=room, env=o.env_for(room))
        except subprocess.TimeoutExpired:
            print(f"  {name}: timed out", file=sys.stderr, flush=True)
            return None
        try:
            reply = json.loads(p.stdout)
        except ValueError:
            print(f"  {name}: unreadable reply, exit {p.returncode}: {(p.stderr or p.stdout)[-200:]!r}", file=sys.stderr, flush=True)
            return None
        models = list(reply.get("modelUsage") or {})
        if not any("sonnet" in m for m in models):   # also what a usage limit looks like
            print(f"  {name}: answered as {models}: {(reply.get('result') or '')[-160:]!r}", file=sys.stderr, flush=True)
            return None
        (room / "CHANGE.diff").unlink(missing_ok=True)
        patch = o.git("diff", cwd=room)
        harm = [b for b in o.run_tests(room, task)["bad"] if b not in before]
        got = regrade.grade(room, task)
    return {**call, "wrap": WRAP_SHA, "lists": o.sha(LISTS), "position": position(call["pr"], call["rep"]) if call["arm"].startswith("ten") else None,
            "passed": got["passed"], "summary": got["summary"], "edited": bool(patch), "harm": harm, "patch": patch[:20000], "said": (reply.get("result") or "")[-600:],
            "model": models, "turns": reply.get("num_turns"), "seconds": round(time.monotonic() - start, 1),
            "api_priced_usd": reply.get("total_cost_usd", 0), "okl_commit": o.git("rev-parse", "HEAD").strip()}


def run() -> int:
    """Make every session without a result yet; stops when sessions keep failing (a usage limit)."""
    by_pr, have = {t["pr"]: t for t in o.tasks()}, kept()
    before = {p: regrade.frozen_failures(t) for p, t in by_pr.items()}
    todo = [c for c in calls() if o.ident(c) not in have]
    print(f"{len(todo)} of {len(calls())} sessions to run (words {WRAP_SHA}, lists {o.sha(LISTS)})", file=sys.stderr, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=o.WORKERS) as pool:
        futures = {pool.submit(session, c, by_pr[c["pr"]], before[c["pr"]]): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= o.STOP_AFTER_EMPTY:
                print(f"stopped: {empty} sessions in a row gave no result", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def reading(rate: dict[str, float], complete: bool) -> str:
    """The stated reading, against the alone-and-told arm in the same sitting."""
    if not complete:
        return "not complete"
    floor = rate["alone_told"] - HOLDS_WITHIN
    if rate["ten_plain"] >= floor:
        return "holds in a list"
    return "the sentence rescues it" if rate["ten_told"] >= floor else "collapses in a list"


def score(write: bool) -> int:
    """Pass rates per arm, averaged over tasks, and the stated reading."""
    guard = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in o.tasks()]
    per_task = {a: {p: round(mean(r["passed"] for r in rows if r["arm"] == a and r["pr"] == p), 3) for p in prs} for a in ARMS}
    rate = {a: round(mean(per_task[a].values()), 3) for a in ARMS}
    complete = len(rows) >= MIN_COMPLETE
    out = {"section": "4ax", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "words": WRAP_SHA, "lists": o.sha(LISTS), "sessions": len(rows), "of": len(calls()),
           "pass_rate": rate, "per_task": per_task, "reading": reading(rate, complete),
           "edited": {a: sum(r["edited"] for r in rows if r["arm"] == a) for a in ARMS}, "sessions_per_arm": {a: sum(r["arm"] == a for r in rows) for a in ARMS},
           "sessions_with_harm": {a: sum(bool(r["harm"]) for r in rows if r["arm"] == a) for a in ARMS},
           "api_priced_usd": round(sum(r["api_priced_usd"] for r in rows), 2), "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None,
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "arm", "rep", "position", "passed", "edited", "harm", "turns", "seconds", "summary", "said", "model")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"replay-list-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(o.REPO)}")
    return 0 if len(rows) == len(calls()) else 2


def main() -> int:
    """run or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["run", "score"])
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return run() if a.step == "run" else score(a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
