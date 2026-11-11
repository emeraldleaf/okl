#!/usr/bin/env python3
"""REPORT §4aw's amendment: grade the kept sessions by behaviour, from each session's saved patch.

    python3 evals/outcome_regrade.py check            # no sessions read: each grader fails frozen, passes fixed
    python3 evals/outcome_regrade.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_replay as o
import run_guard

GRADERS = o.REPO / "tests" / "replay_graders_4aw.py"
CHECK = o.REPO / "evals" / "results" / "outcome-regrade-check-4aw.json"
KEYWORD = {168: "test_pr168", 196: "test_pr196", 198: "test_pr198", 309: "test_pr309"}


def grade(room: Path, task: dict) -> dict:
    """Run a task's grader in `room`: #115's own test (it fails by assertion), a behaviour test for the rest."""
    if task["pr"] == 115:
        o.overlay(room, task)
        target, key = task["test_file"], task["grader"]
    else:
        shutil.copy(GRADERS, room / "tests" / "test_replay_grader.py")
        target, key = "tests/test_replay_grader.py", KEYWORD[task["pr"]]
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line", "-rfE", "-k", key, target],
                       cwd=room, capture_output=True, text=True, env=o.env_for(room), timeout=o.TIMEOUT)
    tail = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr.strip()[-200:]
    return {"passed": p.returncode == 0 and " passed" in tail, "exit": p.returncode, "summary": tail,
            "bad": [m.group(2) for line in p.stdout.splitlines() if (m := re.match(r"^(FAILED|ERROR) (\S+)", line))]}


def check() -> int:
    """No sessions read: each grader must fail on the frozen code and pass on the real fix."""
    run = run_guard.start()
    ok, rows = True, []
    for t in o.tasks():
        with o.room_at(t["frozen"]) as room:
            before = grade(room, t)
        with o.room_at(t["end"]) as room:
            after = grade(room, t)
        good = not before["passed"] and after["passed"]
        ok = ok and good
        print(f"#{t['pr']}: {'ok' if good else 'BAD'} | frozen: {before['summary']} {before['bad']} | fixed: {after['summary']} {after['bad']}", flush=True)
        rows.append({"pr": t["pr"], "fails_frozen": not before["passed"], "passes_fixed": after["passed"], "frozen": before["summary"],
                     "frozen_bad": before["bad"], "fixed": after["summary"]})
    CHECK.write_text(json.dumps(run.stamp({"section": "4aw amendment", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                                           "graders": hashlib.sha256(GRADERS.read_bytes()).hexdigest()[:16], "tasks": rows}), indent=1) + "\n")
    return 0 if ok else 1


def frozen_failures(task: dict) -> set[str]:
    """Tests in the task's file that already fail on the frozen code."""
    with o.room_at(task["frozen"]) as room:
        return set(o.run_tests(room, task)["bad"])


def regrade(row: dict, task: dict, before: set[str]) -> dict:
    """Apply a session's saved patch to the frozen code and grade it."""
    with o.room_at(task["frozen"]) as room:
        applied = True
        if row["patch"]:
            p = subprocess.run(["git", "-C", str(room), "apply", "--whitespace=nowarn", "-"], input=row["patch"], capture_output=True, text=True)
            applied = p.returncode == 0
        harm = [b for b in o.run_tests(room, task)["bad"] if b not in before]
        got = grade(room, task)
    in_patch = set(re.findall(r"^diff --git a/(\S+) ", row["patch"], re.M))
    return {"pr": row["pr"], "arm": row["arm"], "rep": row["rep"], "edited": bool(row["patch"]), "applied": applied, "passed": got["passed"] and applied,
            "harm": harm, "not_in_patch": [c for c in row["changed"] if c not in in_patch], "truncated": row["patch_chars"] > len(row["patch"]), "summary": got["summary"]}


def score(write: bool) -> int:
    """Pass rates per arm, averaged over tasks, against the stated reading."""
    run = run_guard.start()
    tasks = {t["pr"]: t for t in o.tasks()}
    before = {p: frozen_failures(t) for p, t in tasks.items()}
    kept = list(o.kept().values())
    rows = [regrade(r, tasks[r["pr"]], before[r["pr"]]) for r in kept]
    prs = sorted(tasks)
    per_task = {a: {p: round(mean(r["passed"] for r in rows if r["arm"] == a and r["pr"] == p), 3) for p in prs} for a in o.ARMS}
    arm = {a: round(mean(per_task[a].values()), 3) for a in o.ARMS}
    wins = sum(per_task["C"][p] >= per_task["T"][p] for p in prs)
    gain = round(arm["C"] - arm["T"], 3)
    out = {"section": "4aw amendment", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "prompt": o.PROMPT_SHA, "contracts": o.sha(o.CONTRACTS),
           "graders": hashlib.sha256(GRADERS.read_bytes()).hexdigest()[:16], "sessions": len(rows), "of": len(o.calls()),
           "pass_rate": arm, "per_task": per_task, "shown_helps": round(arm["T"] - arm["N"], 3), "contract_gain": gain, "example_gain": round(arm["D"] - arm["C"], 3),
           "contract_at_least_today_on": wins, "lead": len(rows) >= o.MIN_COMPLETE and gain >= o.LEAD_GAIN and wins >= len(prs) - 1,
           "edited": {a: sum(r["edited"] for r in rows if r["arm"] == a) for a in o.ARMS}, "sessions_per_arm": {a: sum(r["arm"] == a for r in rows) for a in o.ARMS},
           "sessions_with_harm": {a: sum(bool(r["harm"]) for r in rows if r["arm"] == a) for a in o.ARMS},
           "patch_did_not_apply": sum(not r["applied"] for r in rows), "truncated": sum(r["truncated"] for r in rows),
           "api_priced_usd": round(sum(r["api_priced_usd"] for r in kept), 2), "median_seconds": sorted(r["seconds"] for r in kept)[len(kept) // 2],
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "rows": rows}
    out = run.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"outcome-replay-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(o.REPO)}")
    return 0 if len(rows) == len(o.calls()) else 2


def main() -> int:
    """check or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["check", "score"])
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return check() if a.step == "check" else score(a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
