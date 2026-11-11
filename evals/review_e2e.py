#!/usr/bin/env python3
"""REPORT §4az: the review after writing, end to end, with the agent choosing the lessons itself.

§4aw's five tasks. Each session is asked to get the change ready to merge, and in two arms also to
run the repository's review after writing: `okl check --change` as it renders for that change over
the lessons as they stood, with every lesson's full text in a folder, since okl is not installed in
the copy. Nothing hands the agent the right lesson. The old steps check the picked lessons in one
pass; the new ones in a fresh sub-agent each (#427).

    python3 evals/review_e2e.py run
    python3 evals/review_e2e.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import default_read as dr
import explain_search as es
import outcome_regrade as regrade
import outcome_replay as o
import run_guard

from okl import core

OUT = o.REPO / "evals" / "bench" / "private" / "realwork" / "review-e2e-4az.jsonl"
ARMS = ("none", "review_one_pass", "review_each_alone")
OLD_STEPS = (   # the steps before #427, as main had them, frozen so this receipt stays reproducible
    "Say what the changed code does, one mechanism per sentence: what it calls and from where, what it "
    "reads and writes (files, databases, environment, network, output), what it assumes, how it fails "
    "and what it returns or prints then, what its tests check and with what data, and what the docs it "
    "changes now claim.",
    "From the lessons below, pick the ten this change is most likely to break: the ones about something "
    "the code does. Any that govern a file it touched are listed first, and are read as well.",
    "Read each with `okl show <id>` (the okl_get tool) and check the code against all of it.",
    "Change the code only where it breaks one, and run its tests again after any change. Where a lesson "
    "does not apply, or the code already does what it says, leave the code alone.",
    "Say which lessons you checked, what you changed for each, and why the rest needed nothing.",
)
NEW_STEPS = core.REVIEW_STEPS
STEPS = {"review_one_pass": OLD_STEPS, "review_each_alone": NEW_STEPS}
ASK = f"""
Before you finish, this repository asks you to run its review after writing. Its output, as `okl check --change` prints it for this change, is in {dr.LIST_FILE}: follow its steps. okl is not installed in this copy, so wherever a step says `okl show <id>`, read the lesson's full text at {dr.LESSON_DIR}/<id>.md instead.
"""
TOOLS = ["claude", "-p", "--model", "sonnet", "--output-format", "stream-json", "--verbose", "--restricted", "--strict-mcp-config",
         "--tools", "Read,Grep,Glob,Edit,Write,Bash,Agent",
         "--allowedTools", "Read", "Grep", "Glob", "Edit", "Write", "Agent", "Bash(python3 -m pytest *)", "Bash(git diff *)", "Bash(git status *)"]
INSTRUMENT = hashlib.sha256(json.dumps([ASK, list(OLD_STEPS), list(NEW_STEPS), TOOLS]).encode()).hexdigest()[:16]
HALF = {"4al": "dev", "4aq": "test"}
DEFAULT_GAIN, OVER_ONE_PASS, EXTRA_HARM, FOLLOWED, MIN_COMPLETE = 0.25, 0.15, 2, 0.5, 68


def review_md(task: dict, arm: str, db: Path, files: list[str]) -> str:
    """The review as `okl check --change` renders it for this change, with the arm's steps."""
    text = dr.review_text(task, db, files)
    rendered = "\n".join(f"{i}. {s}" for i, s in enumerate(NEW_STEPS, 1))
    assert rendered in text, "the renderer's steps moved"
    return text.replace(rendered, "\n".join(f"{i}. {s}" for i, s in enumerate(STEPS[arm], 1)))


def calls() -> list[dict]:
    """Every session, in a seeded order, so stopping early does not favour an arm."""
    out = [{"pr": t["pr"], "arm": a, "rep": r} for t in o.tasks() for a in ARMS for r in range(o.REPEATS)]
    random.Random(o.SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def kept() -> dict[tuple, dict]:
    """Every session kept under this instrument."""
    if not OUT.exists():
        return {}
    return {o.ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if r.get("instrument") == INSTRUMENT}


def stream(stdout: str) -> tuple[dict | None, int]:
    """The final result event of a stream-json run, and how many sub-agents it started."""
    result, agents = None, 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            result = event
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") in ("Agent", "Task"):
                agents += 1
    return result, agents


def session(call: dict, task: dict, before: set[str]) -> dict | None:
    """One session, with or without the review, then the grader on what it left."""
    start, name = time.monotonic(), f"#{call['pr']} {call['arm']}{call['rep']}"
    frozen = {x["pr"]: x for x in es.tasks_of(HALF[task["set"]])}[task["pr"]]
    with tempfile.TemporaryDirectory(prefix="okl-4az-store-") as side, o.room_at(task["frozen"]) as room:
        diff = o.git("diff", task["base"], task["frozen"])
        (room / "CHANGE.diff").write_text(diff)
        ask = ""
        if call["arm"] != "none":
            db = es.store_for(HALF[task["set"]], frozen, Path(side))
            (room / dr.LIST_FILE).write_text(review_md(frozen, call["arm"], db, dr.changed_files(diff)))
            (room / dr.LESSON_DIR).mkdir()
            for i, text in dr.full_text(db).items():
                (room / dr.LESSON_DIR / f"{i.replace('/', '_')}.md").write_text(text)
            ask = ASK
        prompt = o.PROMPT.format(task=o.task_words(task), lesson=ask)
        try:
            p = subprocess.run(TOOLS, input=prompt, capture_output=True, text=True, timeout=3 * o.TIMEOUT, cwd=room, env=o.env_for(room))
        except subprocess.TimeoutExpired:
            print(f"  {name}: timed out", file=sys.stderr, flush=True)
            return None
        reply, agents = stream(p.stdout)
        if not reply or not any("sonnet" in m for m in reply.get("modelUsage") or {}):
            print(f"  {name}: no usable reply, exit {p.returncode}: {((reply or {}).get('result') or p.stderr or '')[-160:]!r}", file=sys.stderr, flush=True)
            return None
        for extra in ("CHANGE.diff", dr.LIST_FILE):
            (room / extra).unlink(missing_ok=True)
        if (room / dr.LESSON_DIR).exists():
            subprocess.run(["rm", "-rf", str(room / dr.LESSON_DIR)], check=True)
        patch = o.git("diff", cwd=room)
        harm = [b for b in o.run_tests(room, task)["bad"] if b not in before]
        got = regrade.grade(room, task)
    return {**call, "instrument": INSTRUMENT, "passed": got["passed"], "summary": got["summary"], "edited": bool(patch), "harm": harm,
            "sub_agents": agents, "patch": patch[:20000], "said": (reply.get("result") or "")[-800:], "turns": reply.get("num_turns"),
            "seconds": round(time.monotonic() - start, 1), "api_priced_usd": reply.get("total_cost_usd", 0), "okl_commit": o.git("rev-parse", "HEAD").strip()}


def run() -> int:
    """Make every session without a result yet; stops when sessions keep failing (a usage limit)."""
    by_pr, have = {t["pr"]: t for t in o.tasks()}, kept()
    before = {p: regrade.frozen_failures(t) for p, t in by_pr.items()}
    todo = [c for c in calls() if o.ident(c) not in have]
    print(f"{len(todo)} of {len(calls())} sessions to run (instrument {INSTRUMENT})", file=sys.stderr, flush=True)
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


def reading(rate: dict[str, float], complete: bool, followed: float, harm: dict[str, int]) -> str:
    """The stated reading, against the arms in the same sitting."""
    if not complete:
        return "not complete"
    if followed < FOLLOWED:
        return "the new steps were not followed"
    better = rate["review_each_alone"] - rate["review_one_pass"] >= OVER_ONE_PASS
    useful = rate["review_each_alone"] - rate["none"] >= DEFAULT_GAIN
    quiet = harm["review_each_alone"] <= harm["review_one_pass"] + EXTRA_HARM
    return "on by default" if better and useful and quiet else "stays opt-in"


def score(write: bool) -> int:
    """Pass rates per arm, sub-agent use, harm and cost, and the stated reading."""
    guard = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in o.tasks()]
    per_task = {a: {p: round(mean(r["passed"] for r in rows if r["arm"] == a and r["pr"] == p), 3) for p in prs
                    if any(r["arm"] == a and r["pr"] == p for r in rows)} for a in ARMS}
    rate = {a: round(mean(per_task[a].values()), 3) if per_task[a] else 0.0 for a in ARMS}
    alone = [r for r in rows if r["arm"] == "review_each_alone"]
    followed = sum(r["sub_agents"] > 0 for r in alone) / len(alone) if alone else 0.0
    harm = {a: sum(bool(r["harm"]) for r in rows if r["arm"] == a) for a in ARMS}
    by_arm = {a: [r for r in rows if r["arm"] == a] for a in ARMS}
    out = {"section": "4az", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "instrument": INSTRUMENT, "sessions": len(rows), "of": len(calls()),
           "pass_rate": rate, "per_task": per_task, "reading": reading(rate, len(rows) >= MIN_COMPLETE, followed, harm),
           "sessions_started_a_sub_agent": round(followed, 3), "sub_agents_median": median(r["sub_agents"] for r in alone) if alone else None,
           "sessions_with_harm": harm, "edited": {a: sum(r["edited"] for r in by_arm[a]) for a in ARMS}, "sessions_per_arm": {a: len(by_arm[a]) for a in ARMS},
           "usd_per_session": {a: round(mean(r["api_priced_usd"] for r in by_arm[a]), 3) for a in ARMS if by_arm[a]},
           "median_seconds": {a: median(r["seconds"] for r in by_arm[a]) for a in ARMS if by_arm[a]},
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "arm", "rep", "passed", "edited", "harm", "sub_agents", "turns", "seconds", "summary", "said")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"review-e2e-{datetime.now(UTC):%Y%m%d-%H%M}.json"
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
