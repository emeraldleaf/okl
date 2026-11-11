#!/usr/bin/env python3
"""REPORT §4ba: does a plan written before any code find the lesson a change needs?

§4aw's five tasks. A picker given every lesson's one line names the ten a change most needs, from
one of three starting points: the task as its author wrote it, a plan the agent writes in the
repository before any code exists, or the finished change as a diff. A hit is the task's lesson
among the ten. No model grades anything.

    python3 evals/plan_reach.py run
    python3 evals/plan_reach.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import explain_search as es
import outcome_replay as o
import run_guard

OUT = o.REPO / "evals" / "bench" / "private" / "realwork" / "plan-reach-4ba.jsonl"
ARMS = ("task", "plan", "diff")
HALF = {"4al": "dev", "4aq": "test"}
DIFF_CUT, K = 40_000, 10
PLAN_PROMPT = """You are about to make the change described below in this repository. Do not write or change any code. Read what you need, then write a short plan: the files you will change or add, and for each, what the new code will do, one mechanism per sentence: what it calls and from where, what it reads and writes (files, databases, environment, network, output), what it assumes, how it fails and what it returns or prints then, and what its tests will check.

The change:
{task}

Answer with a JSON array of at most 25 strings, one sentence each, and nothing after it."""
PICK_PROMPT = """Below are two parts. First, one change: {kind}. Then every lesson this team keeps, one per line: id | title — what to do.

Name the {k} lessons this change most needs to follow, the ones most likely to be broken by it, most likely first.

Answer with a JSON array of {k} lesson ids, and nothing after it.

## The change
{change}

## The lessons
{lessons}"""
KIND = {"task": "the task as its author wrote it, before any code", "plan": "a plan for it, written before any code",
        "diff": "the finished change, as a unified diff"}
INSTRUMENT = hashlib.sha256((PLAN_PROMPT + PICK_PROMPT + json.dumps(KIND)).encode()).hexdigest()[:16]
SONNET = ["claude", "-p", "--model", "sonnet", "--output-format", "json", "--restricted", "--strict-mcp-config"]
LEAD, OVER_TASK, MIN_COMPLETE = 0.6, 0.25, 68


def ask(cmd: list[str], prompt: str, cwd: Path | None = None) -> str | None:
    """One model call's text, or None (a usage limit looks like this)."""
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=o.TIMEOUT, cwd=cwd)
        reply = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return None
    if not any("sonnet" in m for m in reply.get("modelUsage") or {}):
        return None
    return reply.get("result") or ""


def last_array(text: str) -> list[str] | None:
    """The last JSON array of strings in a reply."""
    decoder, found = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch == "[":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, list) and obj and all(isinstance(x, str) for x in obj):
                found = obj
    return found


def calls() -> list[dict]:
    """Every pick, in a seeded order."""
    out = [{"pr": t["pr"], "arm": a, "rep": r} for t in o.tasks() for a in ARMS for r in range(o.REPEATS)]
    random.Random(o.SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def kept() -> dict[tuple, dict]:
    """Every pick kept under this instrument."""
    if not OUT.exists():
        return {}
    return {o.ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if r.get("instrument") == INSTRUMENT}


def change_text(call: dict, task: dict) -> tuple[str | None, list[str] | None]:
    """What the picker reads for this arm, and the plan when there is one."""
    if call["arm"] == "task":
        return o.task_words(task), None
    if call["arm"] == "diff":
        return o.git("diff", task["base"], task["frozen"])[:DIFF_CUT], None
    read_only = [*SONNET, "--tools", "Read,Grep,Glob"]
    with o.room_at(task["base"]) as room:
        text = ask(read_only, PLAN_PROMPT.format(task=o.task_words(task)), cwd=room)
    plan = last_array(text or "")
    return ("\n".join(f"- {s}" for s in plan), plan) if plan else (None, None)


def pick(call: dict, task: dict) -> dict | None:
    """One pick of ten from this arm's starting point."""
    frozen = {x["pr"]: x for x in es.tasks_of(HALF[task["set"]])}[task["pr"]]
    change, plan = change_text(call, task)
    if change is None:
        print(f"  #{call['pr']} {call['arm']}{call['rep']}: no plan", file=sys.stderr, flush=True)
        return None
    lines = es.lesson_lines(HALF[task["set"]], frozen)
    text = ask([*SONNET, "--tools", ""], PICK_PROMPT.format(kind=KIND[call["arm"]], k=K, change=change, lessons="\n".join(lines)))
    picked = last_array(text or "")
    if not picked:
        print(f"  #{call['pr']} {call['arm']}{call['rep']}: no pick", file=sys.stderr, flush=True)
        return None
    known = {line.split(" | ", 1)[0] for line in lines}
    picked = [i for i in picked if i in known][:K]
    return {**call, "instrument": INSTRUMENT, "picked": picked, "hit": task["lesson"] in picked,
            "rank": picked.index(task["lesson"]) + 1 if task["lesson"] in picked else None, "plan": plan, "lessons_listed": len(lines)}


def run() -> int:
    """Make every pick without a result yet; stops when calls keep failing (a usage limit)."""
    by_pr, have = {t["pr"]: t for t in o.tasks()}, kept()
    todo = [c for c in calls() if o.ident(c) not in have]
    print(f"{len(todo)} of {len(calls())} picks to make (instrument {INSTRUMENT})", file=sys.stderr, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=o.WORKERS) as pool:
        futures = {pool.submit(pick, c, by_pr[c["pr"]]): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= o.STOP_AFTER_EMPTY:
                print(f"stopped: {empty} picks in a row gave no result", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def reading(rate: dict[str, float], complete: bool) -> str:
    """The stated reading: planning is worth building if the plan finds the lesson well, and better than the task's words."""
    if not complete:
        return "not complete"
    return "the plan finds it" if rate["plan"] >= LEAD and rate["plan"] - rate["task"] >= OVER_TASK else "the plan does not find it well enough"


def score(write: bool) -> int:
    """Hit rates per arm, averaged over tasks, and the stated reading."""
    guard = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in o.tasks()]
    per_task = {a: {p: round(mean(r["hit"] for r in rows if r["arm"] == a and r["pr"] == p), 3) for p in prs
                    if any(r["arm"] == a and r["pr"] == p for r in rows)} for a in ARMS}
    rate = {a: round(mean(per_task[a].values()), 3) if per_task[a] else 0.0 for a in ARMS}
    out = {"section": "4ba", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "instrument": INSTRUMENT, "picks": len(rows), "of": len(calls()),
           "hit_rate": rate, "per_task": per_task, "reading": reading(rate, len(rows) >= MIN_COMPLETE),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "arm", "rep", "hit", "rank", "picked", "plan")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"plan-reach-{datetime.now(UTC):%Y%m%d-%H%M}.json"
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
