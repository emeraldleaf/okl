#!/usr/bin/env python3
"""REPORT §4ay: ten lessons asked about one at a time, against the same ten in a list.

§4ax found that a lesson which changes the code alone mostly does not in a list of ten. This hands
over the same ten lessons one at a time: each its own fresh session, with the edits carrying
forward, asked only about that lesson. The list and the lesson alone are re-run in the same sitting.

    python3 evals/replay_one.py run
    python3 evals/replay_one.py score [--receipt]
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
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_regrade as regrade
import outcome_replay as o
import replay_list as rl
import run_guard

OUT = o.REPO / "evals" / "bench" / "private" / "realwork" / "outcome-one-4ay.jsonl"
ONE = "one_at_a_time"
ARMS = ("alone_told", "ten_plain", ONE)
ASK = ("This team keeps the lesson below. Check this change against it: if the change breaks it, fix that; "
       "if it does not, or the lesson has no bearing on this change, change nothing for it.")
ASK_SHA = hashlib.sha256(ASK.encode()).hexdigest()[:16]
GAIN, WITHIN, MAX_OTHER_EDITS, EXTRA_HARM, MIN_COMPLETE = 0.25, 0.15, 2, 2, 68


def order(task: dict, rep: int) -> list[tuple[bool, str]]:
    """The ten lessons in §4ax's order for this session, each marked whether it is the right one."""
    others = [(False, x["text"].strip()) for x in json.loads(rl.LISTS.read_text())[str(task["pr"])]["others"]]
    others.insert(rl.position(task["pr"], rep), (True, task["lesson_text"].strip()))
    return others


def calls() -> list[dict]:
    """Every session, in a seeded order, so stopping early does not favour an arm."""
    out = [{"pr": t["pr"], "arm": a, "rep": r} for t in o.tasks() for a in ARMS for r in range(o.REPEATS)]
    random.Random(o.SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def kept() -> dict[tuple, dict]:
    """Every session kept under this question and these lists."""
    if not OUT.exists():
        return {}
    want = (ASK_SHA, o.sha(rl.LISTS))
    return {o.ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if (r.get("ask"), r.get("lists")) == want}


def state(room: Path) -> str:
    """What the working copy holds beyond the frozen commit, new files included."""
    return o.git("status", "--porcelain", cwd=room) + o.git("diff", cwd=room)


def ask(room: Path, prompt: str, name: str) -> dict | None:
    """One fresh agent session; None when it gave no usable reply, which is also what a usage limit looks like."""
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
    if not any("sonnet" in m for m in reply.get("modelUsage") or {}):
        print(f"  {name}: no sonnet in the reply: {(reply.get('result') or '')[-160:]!r}", file=sys.stderr, flush=True)
        return None
    return reply


def one_session(call: dict, task: dict, before: set[str]) -> dict | None:
    """Ten fresh sessions in one working copy, one lesson each, then the grader on what they leave."""
    start, passes = time.monotonic(), []
    with o.room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(o.git("diff", task["base"], task["frozen"]))
        for i, (right, text) in enumerate(order(task, call["rep"])):
            was = state(room)
            section = f"\n{ASK}\n\n<lesson>\n{text}\n</lesson>\n"
            reply = ask(room, o.PROMPT.format(task=o.task_words(task), lesson=section), f"#{call['pr']} one{call['rep']} pass {i}")
            if reply is None:
                return None
            passes.append({"position": i, "right": right, "edited": state(room) != was, "turns": reply.get("num_turns"),
                           "usd": reply.get("total_cost_usd", 0), "said": (reply.get("result") or "")[-300:]})
        (room / "CHANGE.diff").unlink(missing_ok=True)
        patch = o.git("diff", cwd=room)
        harm = [b for b in o.run_tests(room, task)["bad"] if b not in before]
        got = regrade.grade(room, task)
    others = [p for p in passes if not p["right"]]
    return {**call, "passed": got["passed"], "summary": got["summary"], "edited": bool(patch), "harm": harm, "patch": patch[:20000],
            "right_edited": any(p["edited"] for p in passes if p["right"]), "other_edits": sum(p["edited"] for p in others), "passes": passes,
            "seconds": round(time.monotonic() - start, 1), "api_priced_usd": sum(p["usd"] for p in passes)}


def session(call: dict, task: dict, before: set[str]) -> dict | None:
    """One session of any arm, stamped with what it ran under."""
    row = one_session(call, task, before) if call["arm"] == ONE else rl.session(call, task, before)
    return {**row, "ask": ASK_SHA, "lists": o.sha(rl.LISTS), "okl_commit": o.git("rev-parse", "HEAD").strip()} if row else None


def run() -> int:
    """Make every session without a result yet; stops when sessions keep failing (a usage limit)."""
    by_pr, have = {t["pr"]: t for t in o.tasks()}, kept()
    before = {p: regrade.frozen_failures(t) for p, t in by_pr.items()}
    todo = [c for c in calls() if o.ident(c) not in have]
    print(f"{len(todo)} of {len(calls())} sessions to run (question {ASK_SHA})", file=sys.stderr, flush=True)
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


def reading(rate: dict[str, float], complete: bool, other_edits: float, harm: dict[str, int]) -> str:
    """The stated reading, against the list and the lesson alone in the same sitting."""
    if not complete:
        return "not complete"
    if rate[ONE] < rate["ten_plain"] + GAIN:
        return "no better than the list"
    if rate[ONE] < rate["alone_told"] - WITHIN:
        return "better than the list, short of alone"
    quiet = other_edits <= MAX_OTHER_EDITS and harm[ONE] <= harm["ten_plain"] + EXTRA_HARM
    return "works" if quiet else "catches it, but noisy"


def score(write: bool) -> int:
    """Pass rates per arm, averaged over tasks, what the other nine lessons caused, and the reading."""
    guard = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in o.tasks()]
    per_task = {a: {p: round(mean(r["passed"] for r in rows if r["arm"] == a and r["pr"] == p), 3) for p in prs} for a in ARMS}
    rate = {a: round(mean(per_task[a].values()), 3) for a in ARMS}
    ones = [r for r in rows if r["arm"] == ONE]
    other_edits = median(r["other_edits"] for r in ones) if ones else 0
    harm = {a: sum(bool(r["harm"]) for r in rows if r["arm"] == a) for a in ARMS}
    complete = len(rows) >= MIN_COMPLETE
    out = {"section": "4ay", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "question": ASK_SHA, "lists": o.sha(rl.LISTS), "sessions": len(rows), "of": len(calls()),
           "pass_rate": rate, "per_task": per_task, "reading": reading(rate, complete, other_edits, harm), "sessions_with_harm": harm,
           "edited": {a: sum(r["edited"] for r in rows if r["arm"] == a) for a in ARMS}, "sessions_per_arm": {a: sum(r["arm"] == a for r in rows) for a in ARMS},
           "other_edits_median": other_edits, "other_edits_total": sum(r["other_edits"] for r in ones), "other_passes": 9 * len(ones),
           "right_lesson_edited": sum(r["right_edited"] for r in ones), "api_priced_usd": round(sum(r["api_priced_usd"] for r in rows), 2),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "arm", "rep", "passed", "edited", "harm", "right_edited", "other_edits", "seconds", "summary", "passes")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"replay-one-{datetime.now(UTC):%Y%m%d-%H%M}.json"
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
