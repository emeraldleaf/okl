#!/usr/bin/env python3
"""REPORT §4aw: does the way a lesson is written change the code an agent produces?

Five real changes from okl's history, each frozen before review found a defect, where a test the
real fix added checks exactly what a lesson already said. An agent is asked to get the change ready
to merge, under one of four arms: no lesson (N), the lesson as `okl show` gives it (T), the lesson
as a contract (C), and the contract with one bad/good/not-applicable example (D). Every lesson arm
is handed the right lesson, so this tests how it is written and not whether it is found. The test
stays hidden from the agent; it grades the tree the agent leaves.

    python3 evals/outcome_replay.py check             # no model calls: each grader fails frozen, passes fixed
    python3 evals/outcome_replay.py run [--limit N]   # the sessions, resumable, in a seeded order
    python3 evals/outcome_replay.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_guard

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "evals" / "replay-tasks-4aw.json"
CONTRACTS = REPO / "evals" / "replay-contracts-4aw.json"
OUT = REPO / "evals" / "bench" / "private" / "realwork" / "outcome-replay-4aw.jsonl"
BASELINE = REPO / "evals" / "results" / "outcome-replay-check-4aw.json"
ARMS, REPEATS, SEED, WORKERS, TIMEOUT, STOP_AFTER_EMPTY = ("N", "T", "C", "D"), 5, 4, 3, 1800, 6
LEAD_GAIN, MIN_COMPLETE = 0.2, 90
AGENT_FILES = (".claude", ".cursor", ".mcp.json", "CLAUDE.md", "AGENTS.md")   # the copy must not brief the model
AGENT = ["claude", "-p", "--model", "sonnet", "--output-format", "json", "--restricted", "--strict-mcp-config",
         "--tools", "Read,Grep,Glob,Edit,Write,Bash",
         "--allowedTools", "Read", "Grep", "Glob", "Edit", "Write", "Bash(python3 -m pytest *)", "Bash(git diff *)",
         "Bash(git status *)"]
PROMPT = """You are finishing a change in this repository. The working copy already has the change applied, and CHANGE.diff shows it against the commit before it.

What the change is for:
{task}

Get it ready to merge: read it, make any code or test changes it still needs, and run its tests with `python3 -m pytest -q <files>`. Do not commit.
{lesson}
When you are done, say in one or two sentences what you changed, or that nothing needed changing."""
LESSON = """
This team keeps the lesson below, and it bears on this change.

<lesson>
{text}
</lesson>
"""
PROMPT_SHA = hashlib.sha256((PROMPT + LESSON).encode()).hexdigest()[:16]


def tasks() -> list[dict]:
    """The five frozen tasks."""
    return json.loads(TASKS.read_text())


def sha(path: Path) -> str:
    """A file's hash, which every session carries."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def lesson_for(task: dict, arm: str) -> str:
    """What an arm is told: nothing, the lesson as stored, its contract, or the contract with an example."""
    if arm == "N":
        return ""
    if arm == "T":
        text = task["lesson_text"].strip()
    else:
        c = json.loads(CONTRACTS.read_text())[task["lesson"]]
        text = c["contract"].strip() if arm == "C" else f"{c['contract'].strip()}\n\nExample:\n{c['example'].strip()}"
    return LESSON.format(text=text)


def task_words(task: dict) -> str:
    """The change's title and its issues, as the author had them."""
    return "\n\n".join([task["title"], *(f"{i['title']}\n{i['body']}" for i in task["issues"])]).strip()


def git(*args: str, cwd: Path = REPO) -> str:
    """Run git and return its output."""
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def env_for(room: Path) -> dict[str, str]:
    """The room's own package ahead of the installed one, and no store from outside."""
    drop = ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    return {**env, "PYTHONPATH": str(room / "src"), "OKL_BRIEFING_LOG": "0",
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}


@contextmanager
def room_at(commit: str) -> Iterator[Path]:
    """A copy of the repository at `commit` with one commit of history, so the fix is not in it."""
    room = Path(tempfile.mkdtemp(prefix="okl-4aw-"))
    try:
        archive = subprocess.run(["git", "-C", str(REPO), "archive", commit], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(room)], input=archive, check=True)
        for name in AGENT_FILES:
            target = room / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        ident = ["-c", "user.email=replay@example.invalid", "-c", "user.name=replay"]
        subprocess.run(["git", "init", "-q", str(room)], check=True)
        subprocess.run(["git", "-C", str(room), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(room), *ident, "commit", "-qm", "frozen", "--no-verify"], check=True)
        yield room
    finally:
        shutil.rmtree(room, ignore_errors=True)


def overlay(room: Path, task: dict) -> None:
    """Lay the real fix's test files over the room, with any wording-only assertion relaxed."""
    for f in task["tests_after"]:
        text = git("show", f"{task['end']}:{f}")
        if f == task["test_file"]:
            for old, new in task["relax"].items():
                assert old in text, (task["pr"], old)
                text = text.replace(old, new)
        (room / f).parent.mkdir(parents=True, exist_ok=True)
        (room / f).write_text(text)


def run_tests(room: Path, task: dict) -> dict:
    """The grader file's outcome: which tests did not pass, and how many ran."""
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line", "-rfE", task["test_file"]],
                       cwd=room, capture_output=True, text=True, env=env_for(room), timeout=TIMEOUT)
    bad = sorted(m.group(2) for line in p.stdout.splitlines() if (m := re.match(r"^(FAILED|ERROR) (\S+)", line)))
    tail = p.stdout.strip().splitlines()[-1:] if p.stdout.strip() else [p.stderr.strip()[-200:]]
    return {"bad": bad, "summary": tail[0], "exit": p.returncode}


def grader_failed(result: dict, task: dict) -> bool:
    """True when the grader test, or any of its parameters, did not pass, or the file did not run."""
    return result["exit"] not in (0, 1) or any(f"::{task['grader']}" in b for b in result["bad"])


def check() -> int:
    """No model calls: each grader must fail on the frozen code and pass on the fixed code."""
    run = run_guard.start()
    rows, ok = [], True
    for t in tasks():
        with room_at(t["frozen"]) as room:
            overlay(room, t)
            before = run_tests(room, t)
        with room_at(t["end"]) as room:
            overlay(room, t)
            after = run_tests(room, t)
        good = grader_failed(before, t) and not grader_failed(after, t)
        ok = ok and good
        rows.append({"pr": t["pr"], "grader": t["grader"], "fails_frozen": grader_failed(before, t), "passes_fixed": not grader_failed(after, t),
                     "already_failing_frozen": [b for b in before["bad"] if f"::{t['grader']}" not in b], "before": before["summary"], "after": after["summary"]})
        print(f"#{t['pr']}: fails frozen {rows[-1]['fails_frozen']}, passes fixed {rows[-1]['passes_fixed']} | {before['summary']} | {after['summary']}", flush=True)
    BASELINE.write_text(json.dumps(run.stamp({"section": "4aw", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "tasks": rows}), indent=1) + "\n")
    return 0 if ok else 1


def calls() -> list[dict]:
    """Every session, in a seeded order, so stopping early does not favour an arm."""
    out = [{"pr": t["pr"], "arm": a, "rep": r} for t in tasks() for a in ARMS for r in range(REPEATS)]
    random.Random(SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def ident(row: dict) -> tuple:
    """A session's identity under this prompt and these contracts."""
    return (row["pr"], row["arm"], row["rep"])


def kept() -> dict[tuple, dict]:
    """Every session kept under this prompt and these contracts."""
    if not OUT.exists():
        return {}
    want = (PROMPT_SHA, sha(CONTRACTS))
    return {ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if (r.get("prompt"), r.get("contracts")) == want}


def session(call: dict, task: dict) -> dict | None:
    """One agent session, then the hidden test on the tree it left."""
    start = time.monotonic()
    with room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(git("diff", task["base"], task["frozen"]))
        prompt = PROMPT.format(task=task_words(task), lesson=lesson_for(task, call["arm"]))
        try:
            p = subprocess.run(AGENT, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=room, env=env_for(room))
        except subprocess.TimeoutExpired:
            print(f"  #{call['pr']} {call['arm']}{call['rep']}: timed out", file=sys.stderr, flush=True)
            return None
        try:
            reply = json.loads(p.stdout)
        except ValueError:
            print(f"  #{call['pr']} {call['arm']}{call['rep']}: unreadable reply, exit {p.returncode}: {(p.stderr or p.stdout)[-200:]!r}", file=sys.stderr, flush=True)
            return None
        models = list(reply.get("modelUsage") or {})
        if not any("sonnet" in m for m in models):   # also what a usage limit looks like
            print(f"  #{call['pr']} {call['arm']}{call['rep']}: answered as {models}: {(reply.get('result') or '')[-160:]!r}", file=sys.stderr, flush=True)
            return None
        (room / "CHANGE.diff").unlink(missing_ok=True)
        changed = [line[3:] for line in git("status", "--porcelain", cwd=room).splitlines()]
        patch = git("diff", cwd=room)
        overlay(room, task)
        result = run_tests(room, task)
    return {**call, "prompt": PROMPT_SHA, "contracts": sha(CONTRACTS), "passed": not grader_failed(result, task), "bad": result["bad"],
            "summary": result["summary"], "changed": changed, "patch_chars": len(patch), "patch": patch[:20000], "said": (reply.get("result") or "")[-600:],
            "model": models, "turns": reply.get("num_turns"), "seconds": round(time.monotonic() - start, 1),
            "api_priced_usd": reply.get("total_cost_usd", 0), "okl_commit": git("rev-parse", "HEAD").strip()}


def run(limit: int | None) -> int:
    """Make every session without a result yet; stops when sessions keep failing (a usage limit)."""
    by_pr, have = {t["pr"]: t for t in tasks()}, kept()
    todo = [c for c in calls() if ident(c) not in have][:limit]
    print(f"{len(todo)} of {len(calls())} sessions to run (prompt {PROMPT_SHA}, contracts {sha(CONTRACTS)})", file=sys.stderr, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(session, c, by_pr[c["pr"]]): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= STOP_AFTER_EMPTY:
                print(f"stopped: {empty} sessions in a row gave no result", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def harm(row: dict, baseline: dict) -> int:
    """Tests in the grader's file that passed on the frozen code and fail on the agent's tree, the grader aside."""
    task = next(t for t in tasks() if t["pr"] == row["pr"])
    before = set(baseline[row["pr"]]["already_failing_frozen"])
    return sum(1 for b in row["bad"] if f"::{task['grader']}" not in b and b not in before)


def score(write: bool) -> int:
    """Pass rates per arm, averaged over tasks, against the stated reading."""
    run_ = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in tasks()]
    baseline = {r["pr"]: r for r in json.loads(BASELINE.read_text())["tasks"]}
    rate = {a: {p: [r["passed"] for r in rows if r["arm"] == a and r["pr"] == p] for p in prs} for a in ARMS}
    per_task = {a: {p: round(mean(v), 3) if v else None for p, v in rate[a].items()} for a in ARMS}
    arm_rate = {a: round(mean(v for v in per_task[a].values() if v is not None), 3) for a in ARMS}
    wins = sum(1 for p in prs if (per_task["C"][p] or 0) >= (per_task["T"][p] or 0))
    harmed = {a: sum(1 for r in rows if r["arm"] == a and harm(r, baseline)) for a in ARMS}
    gain = round(arm_rate["C"] - arm_rate["T"], 3)
    out = {"section": "4aw", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "prompt": PROMPT_SHA, "contracts": sha(CONTRACTS),
           "sessions": len(rows), "of": len(calls()), "complete": len(rows) >= MIN_COMPLETE, "pass_rate": arm_rate, "per_task": per_task,
           "shown_helps": round(arm_rate["T"] - arm_rate["N"], 3), "contract_gain": gain, "example_gain": round(arm_rate["D"] - arm_rate["C"], 3),
           "contract_at_least_today_on": wins, "sessions_with_harm": harmed, "lead": len(rows) >= MIN_COMPLETE and gain >= LEAD_GAIN and wins >= len(prs) - 1,
           "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None, "api_priced_usd": round(sum(r["api_priced_usd"] for r in rows), 2),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "arm", "rep", "passed", "changed", "patch_chars", "turns", "seconds", "summary", "said", "model")} for r in rows]}
    out = run_.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = REPO / "evals" / "results" / f"outcome-replay-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0 if len(rows) == len(calls()) else 2


def main() -> int:
    """check, run or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["check", "run", "score"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    if a.step == "check":
        return check()
    if a.step == "run":
        return run(a.limit)
    return score(a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
