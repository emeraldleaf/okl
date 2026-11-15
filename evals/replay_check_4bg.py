#!/usr/bin/env python3
"""REPORT §4bg: prove each grader of the replay task set fails on the frozen code and passes on the fixed.

No model is called. For every task of evals/replay-tasks-4bg.json it checks out the frozen commit in a
throwaway git worktree, copies tests/replay_graders_4bg.py in as tests/test_replay_grader.py (as the
replay does) and runs that task's grader there, in the environment a replay gives it: none of this
session's CLAUDE*, OKL_*, GIT_* or MCP_* variables, PYTHONPATH on the worktree's own src, the warm
model off, and OKL_BRIEFING_LOG unset. Then the same at the end commit.

  a broken task is valid when its grader fails at `frozen` by an assertion of its own (pytest's exit 1
                   and every failure on a line of the grader file raising AssertionError or Failed: an
                   ImportError, a collection error or a crash inside okl does not count) and passes at `end`;
  a control        (needs_nothing: the frozen code already follows the lesson) is valid when its grader
                   passes at `frozen`. That it fails once the lesson's behaviour is removed is shown by hand
                   with a one-line mutation of a scratch worktree, and reported, not run here.

    python3 evals/replay_check_4bg.py               # every task; writes evals/results/replay-check-4bg-<stamp>.json
    python3 evals/replay_check_4bg.py --only t01 t05 --no-receipt

`--alternatives` asks the other question of the same graders: can they tell a different correct fix from a
plausible wrong one? For each broken task it takes a worktree at `frozen`, applies
evals/replay-alternatives-4bg/<id>-right.patch and runs the grader, then does the same in a fresh worktree
with <id>-wrong.patch (what each patch is, and why the wrong one is wrong, is in that directory's notes.json):

  a task's pair is valid when the right fix passes (pytest's exit 0 with a test run) and the wrong fix fails
                   by an assertion of the grader's own (the rule `frozen` is held to above).

It writes evals/results/replay-alternatives-4bg-<stamp>.json. A right fix that fails means the grader is
over-specific or the fix is wrong; a wrong fix that passes means the grader misses what the fix leaves.
Neither is repaired here: the receipt reports them as they are.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_guard

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "evals" / "replay-tasks-4bg.json"
GRADERS = REPO / "tests" / "replay_graders_4bg.py"
RESULTS = REPO / "evals" / "results"
DROP = ("CLAUDE", "OKL_", "GIT_", "MCP_")
TIMEOUT = 900
SHOW_TAIL = "--tail" in sys.argv
# `pytest --tb=line` prints one `<file>:<line>: <Exception>: <message>` per failure, under FAILURES.
FAILURE_LINE = re.compile(r"^(?P<file>/\S.*?):(?P<line>\d+): (?P<exc>[\w.]+)(?:: (?P<msg>.*))?$")
TEMP_PATH = re.compile(r"(?:/private)?/(?:var/folders/\w+/\w+/T|tmp)/\S+")   # a receipt names no scratch directory
GRADER_FILE = "tests/test_replay_grader.py"
OWN_ASSERTIONS = ("AssertionError", "Failed", "_pytest.outcomes.Failed")
ALTERNATIVES = REPO / "evals" / "replay-alternatives-4bg"


def env_for(tree: Path) -> dict[str, str]:
    """A replay's environment for a grader: nothing of this session's, the tree's code first."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(DROP)}
    env["PYTHONPATH"] = str(tree / "src")
    env["OKL_WARM"] = "0"
    return env


def git(*args: str) -> str:
    """This repository's git output for `args`."""
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


class Tree:
    """A detached worktree of this repository at one commit, in the system temp directory."""

    def __init__(self, commit: str, label: str) -> None:
        self.parent = Path(tempfile.mkdtemp(prefix=f"okl-replay-{label}-"))
        self.path = self.parent / "tree"
        git("worktree", "add", "--detach", str(self.path), commit)

    def close(self) -> None:
        """Remove the worktree and its directory, and prune what git recorded of it."""
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(self.path)],
                       capture_output=True, text=True)
        shutil.rmtree(self.parent, ignore_errors=True)
        subprocess.run(["git", "-C", str(REPO), "worktree", "prune"], capture_output=True, text=True)


def failures_in(output: str) -> list[dict[str, Any]]:
    """Each failure pytest's line format reports: file, line, exception and the start of its message."""
    found, inside = [], False
    for ln in output.splitlines():
        if re.match(r"^=+ FAILURES =+$", ln):
            inside = True
        elif re.match(r"^=+ (short test summary info|\d+ .*) =+$", ln) and inside:
            inside = False
        elif inside and (m := FAILURE_LINE.match(ln)):
            found.append({"file": m["file"], "line": int(m["line"]), "exc": m["exc"],
                          "msg": TEMP_PATH.sub("<tmp>", m["msg"] or "")[:160]})
    return found


def run_grader(tree: Tree, grader: str) -> dict[str, Any]:
    """Copy the graders in as the replay does and run one of them: its exit code and where it failed."""
    shutil.copy(GRADERS, tree.path / GRADER_FILE)
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line", GRADER_FILE, "-k", grader]
    try:
        p = subprocess.run(argv, cwd=tree.path, env=env_for(tree.path), capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"exit": None, "failures": [], "own_assertion": False, "tail": "timed out", "ran": 0}
    out = p.stdout + p.stderr
    fails = failures_in(out)
    own = bool(fails) and all(f["file"].endswith(GRADER_FILE) and f["exc"] in OWN_ASSERTIONS for f in fails)
    ran = re.search(r"(\d+) (?:passed|failed)", out)
    return {"exit": p.returncode, "failures": fails, "own_assertion": own,
            "tail": "\n".join(out.strip().splitlines()[-6:]), "ran": int(ran.group(1)) if ran else 0}


def where(result: dict[str, Any]) -> str | None:
    """The first failing line, as `file:line Exception: message` relative to the tree."""
    if not result["failures"]:
        return None
    f = result["failures"][0]
    return f"{GRADER_FILE}:{f['line']} {f['exc']}: {f['msg']}" if f["file"].endswith(GRADER_FILE) \
        else f"{f['file'].split('/tree/')[-1]}:{f['line']} {f['exc']}: {f['msg']}"


def check(task: dict[str, Any]) -> dict[str, Any]:
    """One task: its grader at the frozen commit and at the end commit, and whether the pair is valid."""
    row: dict[str, Any] = {"id": task["id"], "pr": task["pr"], "grader": task["grader"],
                           "needs_nothing": task["needs_nothing"], "frozen": task["frozen"], "end": task["end"]}
    for name in ("frozen", "end"):
        tree = Tree(task[name], f"{task['id']}-{name}")
        try:
            result = run_grader(tree, task["grader"])
        finally:
            tree.close()
        row[f"exit_{name}"] = result["exit"]
        row[f"line_{name}"] = where(result)
        row[f"ran_{name}"] = result["ran"]
        row[f"own_assertion_{name}"] = result["own_assertion"]
        if SHOW_TAIL or result["exit"] not in (0, 1) or (result["exit"] == 1 and not result["own_assertion"]):
            row[f"tail_{name}"] = result["tail"]
    passes_end = row["exit_end"] == 0 and row["ran_end"] > 0
    if task["needs_nothing"]:
        row["valid"] = row["exit_frozen"] == 0 and row["ran_frozen"] > 0 and passes_end
    else:
        row["valid"] = row["exit_frozen"] == 1 and row["own_assertion_frozen"] and passes_end
    return row


def apply_patch(tree: Tree, patch: Path) -> str | None:
    """Apply `patch` to the tree with git; None when it applied, else why it did not."""
    if not patch.is_file():
        return f"no patch at {patch.relative_to(REPO)}"
    p = subprocess.run(["git", "-C", str(tree.path), "apply", str(patch)], env=env_for(tree.path),
                       capture_output=True, text=True)
    return None if p.returncode == 0 else (p.stderr.strip().splitlines() or ["git apply failed"])[-1][:160]


def try_alternative(task: dict[str, Any], kind: str) -> dict[str, Any]:
    """The grader at the frozen commit with `<id>-<kind>.patch` applied, in a worktree of its own."""
    patch = ALTERNATIVES / f"{task['id']}-{kind}.patch"
    tree = Tree(task["frozen"], f"{task['id']}-{kind}")
    try:
        refused = apply_patch(tree, patch)
        if refused:
            return {"exit": None, "line": f"patch not applied: {refused}", "own_assertion": False, "ran": 0,
                    "tail": refused}
        result = run_grader(tree, task["grader"])
    finally:
        tree.close()
    return {"exit": result["exit"], "line": where(result), "own_assertion": result["own_assertion"],
            "ran": result["ran"], "tail": result["tail"]}


def check_alternatives(task: dict[str, Any]) -> dict[str, Any]:
    """One broken task: its grader on a right fix and on a wrong fix, and whether it told them apart."""
    right, wrong = try_alternative(task, "right"), try_alternative(task, "wrong")
    row: dict[str, Any] = {
        "id": task["id"], "pr": task["pr"], "grader": task["grader"], "frozen": task["frozen"],
        "right_exit": right["exit"], "right_failing_line": right["line"], "right_ran": right["ran"],
        "wrong_exit": wrong["exit"], "wrong_failing_line": wrong["line"], "wrong_ran": wrong["ran"],
        "wrong_own_assertion": wrong["own_assertion"],
        "right_patch_sha256": patch_sha(task["id"], "right"), "wrong_patch_sha256": patch_sha(task["id"], "wrong"),
    }
    row["valid"] = (right["exit"] == 0 and right["ran"] > 0
                    and wrong["exit"] == 1 and wrong["own_assertion"])
    for kind, got in (("right", right), ("wrong", wrong)):
        if SHOW_TAIL or got["exit"] not in (0, 1) or (got["exit"] == 1 and not got["own_assertion"]):
            row[f"{kind}_tail"] = got["tail"]
    return row


def patch_sha(task_id: str, kind: str) -> str | None:
    """The sha256 of one alternative patch, or None when there is none."""
    patch = ALTERNATIVES / f"{task_id}-{kind}.patch"
    return hashlib.sha256(patch.read_bytes()).hexdigest() if patch.is_file() else None


def main_alternatives(tasks: list[dict[str, Any]], no_receipt: bool) -> int:
    """Run each broken task's right and wrong fixes, print one line per task, and write the receipt."""
    broken = [t for t in tasks if not t["needs_nothing"]]
    run = run_guard.start()
    rows = []
    for t in broken:
        row = check_alternatives(t)
        rows.append(row)
        verdict = "told apart" if row["valid"] else "NOT TOLD APART"
        print(f"{t['id']} pr{t['pr']:<4} right exit {row['right_exit']} {row['right_failing_line'] or '-'}"
              f" | wrong exit {row['wrong_exit']} {row['wrong_failing_line'] or '-'} | {verdict}", flush=True)
        for kind in ("right", "wrong"):
            if f"{kind}_tail" in row:
                print(f"   {kind}: {row[f'{kind}_tail']}", flush=True)
    valid = sum(r["valid"] for r in rows)
    print(f"\n{valid}/{len(rows)} told apart")
    if no_receipt:
        return 0 if valid == len(rows) else 1
    receipt = run.stamp({
        "check": "replay-alternatives-4bg", "tasks_file": str(TASKS.relative_to(REPO)),
        "tasks_sha256": hashlib.sha256(TASKS.read_bytes()).hexdigest(),
        "graders_sha256": hashlib.sha256(GRADERS.read_bytes()).hexdigest(),
        "alternatives_dir": str(ALTERNATIVES.relative_to(REPO)),
        "dropped_env_prefixes": list(DROP), "pytest_k": "the grader's name", "python": sys.version.split()[0],
        "tasks_checked": [r["id"] for r in rows], "valid": valid, "of": len(rows),
        "all_valid": valid == len(rows), "rows": rows,
    })
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"replay-alternatives-4bg-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.json"
    path.write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"wrote {path.relative_to(REPO)}")
    return 0 if receipt["all_valid"] and receipt.get("usable", True) else 1


def main() -> int:
    """Check each task, print one line per task, and write the receipt; 1 when any task is not valid."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=[], help="task ids to check (default: all)")
    ap.add_argument("--no-receipt", action="store_true", help="print only; write no receipt")
    ap.add_argument("--tail", action="store_true", help="also print the end of each pytest run")
    ap.add_argument("--alternatives", action="store_true",
                    help="instead: run each broken task's grader on a right and a wrong fix of the frozen code")
    args = ap.parse_args()
    every = json.loads(TASKS.read_text())
    unknown = sorted(set(args.only) - {t["id"] for t in every})
    if unknown:
        # A selector that matches nothing must not report 0/0 as all valid (review of #454).
        print(f"replay_check_4bg: no such task: {', '.join(unknown)}", file=sys.stderr)
        return 2
    tasks = [t for t in every if not args.only or t["id"] in args.only]
    if args.alternatives and not any(not t.get("needs_nothing") for t in tasks):
        print("replay_check_4bg: the tasks selected are all controls, which have no alternative fixes", file=sys.stderr)
        return 2
    if args.alternatives:
        return main_alternatives(tasks, args.no_receipt)
    run = run_guard.start()
    rows = []
    for t in tasks:
        row = check(t)
        rows.append(row)
        verdict = "valid" if row["valid"] else "INVALID"
        print(f"{t['id']} pr{t['pr']:<4} frozen exit {row['exit_frozen']} {row['line_frozen'] or '-'}"
              f" | end exit {row['exit_end']} {row['line_end'] or '-'} | {verdict}", flush=True)
        for name in ("frozen", "end"):
            if f"tail_{name}" in row:
                print(f"   {name}: {row[f'tail_{name}']}", flush=True)
    valid = sum(r["valid"] for r in rows)
    print(f"\n{valid}/{len(rows)} valid")
    if args.no_receipt:
        return 0 if valid == len(rows) else 1
    receipt = run.stamp({
        "check": "replay-check-4bg", "tasks_file": str(TASKS.relative_to(REPO)),
        "tasks_sha256": hashlib.sha256(TASKS.read_bytes()).hexdigest(),
        "graders_sha256": hashlib.sha256(GRADERS.read_bytes()).hexdigest(),
        "dropped_env_prefixes": list(DROP), "pytest_k": "the grader's name", "python": sys.version.split()[0],
        "tasks_checked": [r["id"] for r in rows], "valid": valid, "of": len(rows),
        "all_valid": valid == len(rows), "rows": rows,
    })
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"replay-check-4bg-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.json"
    path.write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"wrote {path.relative_to(REPO)}")
    return 0 if receipt["all_valid"] and receipt.get("usable", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
