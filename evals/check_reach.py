#!/usr/bin/env python3
"""REPORT §4bd: would a lesson's own check, run at the edit, have caught the breaks past changes made?

`okl on-edit` (#441) runs a lesson's stored check after the agent edits a file the lesson governs. It
can change the code only where the check fails on the edit that breaks the lesson. On §4bc's 58
changes and their 124 broken lessons, this runs each broken lesson's stored check at the change's
merge base and at the change as first written, and sorts the pair: caught (passes at the base, fails
at the change by its own failure), cannot judge (does not pass at the base, or fails at the change
only by not running), or missed (passes at both). No model is called.

    python3 evals/check_reach.py count            # the store's fields only: checks, files (no check runs)
    python3 evals/check_reach.py pilot [--receipt]  # §4aw's five tasks, frozen and fixed (seen before §4bd)
    python3 evals/check_reach.py run              # the registered measurement, resumable
    python3 evals/check_reach.py score [--receipt]
    python3 evals/check_reach.py control [--receipt]   # not registered: can the instrument see a catch?
    python3 evals/check_reach.py rulewide             # §4be: #415's rule-wide checks on the same breaks
    python3 evals/check_reach.py rulewide-score [--receipt]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import explain_search as es
import lesson_review as lr
import run_guard

from okl.cli.verification import _stored_check
from okl.client import Client
from okl.store import path_matches

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "evals" / "results"
REPLAY_TASKS = REPO / "evals" / "replay-tasks-4aw.json"
ROWS = lr.PRIVATE / "check-reach-4bd.jsonl"
TIMEOUT = 600
CATCHES_NEEDED = 13            # 10% of the 124 broken lessons: the reading's bar
NOT_RUNNING = {2, 4, 5, 126, 127}   # pytest collection, usage, empty selection; command or file not found
MISSING = ("No such file or directory", "can't open file", "ERROR: file or directory not found",
           "ModuleNotFoundError")


def env_for(tree: Path) -> dict[str, str]:
    """The check's environment: this tree's code first, no store named (lesson n_119528a07fa5)."""
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN")}
    return {**env, "PYTHONPATH": str(tree / "src"), "OKL_BRIEFING_LOG": "0"}


def run_check(tree: Path, run: str, expect: str | None) -> dict:
    """One run of a stored check in `tree`: whether it passed, and whether it failed by its own
    failure or only by not running. The command is a check `okl verify` stored from a person's
    --run, in this repository's own store (lesson n_adea7f2c7373's designed exception)."""
    started = time.monotonic()
    try:
        p = subprocess.run(run, shell=True, cwd=tree, env=env_for(tree), capture_output=True,
                           text=True, errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"passed": False, "own_failure": False, "why": f"timed out after {TIMEOUT}s",
                "seconds": round(time.monotonic() - started, 1)}
    out = (p.stdout or "") + (p.stderr or "")
    passed = p.returncode == 0 and (not expect or expect in out)
    not_running = p.returncode in NOT_RUNNING or any(m in out for m in MISSING)
    own = not passed and not not_running
    why = ("passed" if passed else f"exit {p.returncode}" if p.returncode else "exit 0, signal missing")
    return {"passed": passed, "own_failure": own, "why": why, "exit": p.returncode,
            "tail": out.strip().splitlines()[-3:], "seconds": round(time.monotonic() - started, 1)}


def sort_pair(at_base: dict, at_change: dict) -> str:
    """caught, cannot_judge or missed, by the registered rule."""
    if not at_base["passed"]:
        return "cannot_judge"
    if at_change["passed"]:
        return "missed"
    return "caught" if at_change["own_failure"] else "cannot_judge"


class Tree:
    """A clean worktree at `commit`, removed afterwards."""

    def __init__(self, commit: str) -> None:
        self.commit = commit
        self.path = Path(tempfile.mkdtemp(prefix="okl-4bd-")) / "tree"

    def __enter__(self) -> Path:
        subprocess.run(["git", "-C", str(REPO), "worktree", "add", "-q", "--detach", str(self.path), self.commit],
                       check=True)
        return self.path

    def __exit__(self, *_exc: object) -> None:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(self.path)], check=False)


def broken_pairs() -> list[dict]:
    """Every (change, broken lesson) of §4bc's set, with the change's commits and paths."""
    out = []
    for half in ("dev", "test"):
        key = es.key_of(half)
        for task in es.tasks_of(half):
            for (pr, lesson), state in key.items():
                if pr == task["pr"] and state == "broken":
                    out.append({"half": half, "pr": pr, "lesson": lesson, "base": task["base"],
                                "commit": task["commit"], "paths": task.get("paths") or []})
    return out


def lessons() -> dict:
    """Every lesson in this checkout's store, by id."""
    return {n.id: n for n in Client().all_nodes()}


def count(_args: argparse.Namespace) -> int:
    """The store's fields for the broken lessons: which carry a stored check, which name files, and
    which name a file their change touched. Runs no check."""
    nodes = lessons()
    pairs = broken_pairs()
    rows = []
    for pr in pairs:
        n = nodes.get(pr["lesson"])
        globs = [g.strip() for g in (n.files or "").split(",") if g.strip()] if n else []
        rows.append({**pr, "has_check": bool(n and _stored_check(n.verified_by)), "has_files": bool(globs),
                     "governs_a_changed_path": any(path_matches(g, p) for g in globs for p in pr["paths"])})
    c = {"broken": len(rows), "changes": len({(r["half"], r["pr"]) for r in rows}),
         "has_check": sum(r["has_check"] for r in rows), "has_files": sum(r["has_files"] for r in rows),
         "governs_a_changed_path": sum(r["governs_a_changed_path"] for r in rows)}
    print(json.dumps(c))
    if getattr(_args, "receipt", False):
        guard = run_guard.start()
        write("check-reach-count", guard.stamp({"section": "4bd, seen while drafting", "counts": c}))
    return 0


def pilot(args: argparse.Namespace) -> int:
    """§4aw's five tasks: each lesson's stored check on the frozen change and on the fix."""
    guard = run_guard.start()
    nodes = lessons()
    rows = []
    for task in json.loads(REPLAY_TASKS.read_text()):
        n = nodes.get(task["lesson"])
        chk = _stored_check(n.verified_by) if n else None
        row = {"pr": task["pr"], "lesson": task["lesson"], "check": chk[0] if chk else None,
               "files": (n.files or "") if n else ""}
        if chk:
            for side in ("frozen", "end"):
                with Tree(task[side]) as tree:
                    row[side] = run_check(tree, *chk)
            row["tells_them_apart"] = row["frozen"]["own_failure"] and row["end"]["passed"]
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("pr", "lesson", "check")} | {
            "frozen": row.get("frozen", {}).get("why"), "end": row.get("end", {}).get("why")}))
    if args.receipt:
        write("check-reach-pilot", guard.stamp({
            "section": "4bd, seen while drafting", "tasks": len(rows), "rows": rows,
            "told_apart": sum(bool(r.get("tells_them_apart")) for r in rows),
            "with_a_check": sum(bool(r["check"]) for r in rows), "with_files": sum(bool(r["files"]) for r in rows)}))
    return 0


def done() -> dict[tuple[str, int, str], dict]:
    """The rows run so far, by (half, change, lesson)."""
    if not ROWS.exists():
        return {}
    rows = [json.loads(x) for x in ROWS.read_text().splitlines() if x.strip()]
    return {(r["half"], r["pr"], r["lesson"]): r for r in rows}


def run(_args: argparse.Namespace) -> int:
    """Each broken lesson with a stored check, at its change's base and at the change; resumable.
    Each row names the okl commit it ran at, so score can tell a run whose code moved (#434)."""
    at = run_guard.start().started[0]
    nodes = lessons()
    have = done()
    todo = [p for p in broken_pairs() if (p["half"], p["pr"], p["lesson"]) not in have
            and p["lesson"] in nodes and _stored_check(nodes[p["lesson"]].verified_by)]
    ROWS.parent.mkdir(parents=True, exist_ok=True)
    by_commit: dict[tuple[str, str], list[dict]] = {}
    for p in todo:
        by_commit.setdefault((p["base"], p["commit"]), []).append(p)
    for (base, commit), group in by_commit.items():
        results: dict[str, dict] = {}
        for side, sha in (("base", base), ("change", commit)):
            with Tree(sha) as tree:
                for p in group:
                    results.setdefault(p["lesson"], {})[side] = run_check(tree, *_stored_check(nodes[p["lesson"]].verified_by))
        with ROWS.open("a") as f:
            for p in group:
                r = results[p["lesson"]]
                row = {**{k: p[k] for k in ("half", "pr", "lesson", "base", "commit")},
                       "check": _stored_check(nodes[p["lesson"]].verified_by)[0],
                       "at_base": r["base"], "at_change": r["change"], "sorted": sort_pair(r["base"], r["change"]),
                       "okl_commit": at}
                f.write(json.dumps(row) + "\n")
                print(f"#{p['pr']} {p['lesson']}: {row['sorted']}", flush=True)
    return 0


def score(args: argparse.Namespace) -> int:
    """The registered measures and reading."""
    guard = run_guard.start()
    pairs = broken_pairs()
    nodes = lessons()
    rows = done()
    sorted_ = Counter(r["sorted"] for r in rows.values())
    caught = [r for r in rows.values() if r["sorted"] == "caught"]

    def governs(r: dict) -> bool:
        n = nodes.get(r["lesson"]); paths = next(p["paths"] for p in pairs if (p["half"], p["pr"], p["lesson"]) ==
                                                  (r["half"], r["pr"], r["lesson"]))
        return bool(n and n.files) and any(path_matches(g.strip(), x) for g in n.files.split(",") if g.strip()
                                           for x in paths)
    per_half = {h: {"broken": sum(p["half"] == h for p in pairs),
                    "caught": sum(r["half"] == h for r in caught)} for h in ("dev", "test")}
    receipt = {"section": "4bd", "broken": len(pairs), "with_a_check": len(rows), "sorted": dict(sorted_),
               "rows_made_at": sorted({r.get("okl_commit") for r in rows.values()} - {None}),
               "cannot_judge_why": dict(Counter(f"base {r['at_base']['why']}; change {r['at_change']['why']}"
                                                for r in rows.values() if r["sorted"] == "cannot_judge")),
               "caught_share": round(len(caught) / len(pairs), 3) if pairs else None,
               "caught_share_of_checked": round(len(caught) / len(rows), 3) if rows else None,
               "caught_governing_a_changed_path": sum(governs(r) for r in caught), "per_half": per_half,
               "check_seconds_at_change": sorted(r["at_change"]["seconds"] for r in rows.values()),
               "reading": ("edit-time checks can reach these breaks" if len(caught) >= CATCHES_NEEDED
                           else "they cannot, as lessons stand"),
               "caught": [{k: r[k] for k in ("half", "pr", "lesson", "check")} for r in caught]}
    print(json.dumps({k: v for k, v in receipt.items() if k not in ("caught", "check_seconds_at_change")}, indent=1))
    if args.receipt:
        write("check-reach", guard.stamp(receipt))
    return 0


def control(args: argparse.Namespace) -> int:
    """Not registered: that the instrument can see a catch at all. A patch §4ah's re-run wrote to break
    doc-check-defaults, which its check failed on, replayed through run_check and sort_pair."""
    guard = run_guard.start()
    source = RESULTS / "drift-mutate-20261101-1935.json"
    d = json.loads(source.read_text())
    row = next(r for r in d["patches"] if r["lesson"] == "doc-check-defaults" and r["kind"] == "breaking"
               and r["check"] == "fail")
    patch = RESULTS / "drift-mutate-20261101-1935-patches" / f"{row['lesson']}-{row['kind']}-{row['k']}.diff"
    run, expect = _stored_check(lessons()[row["lesson"]].verified_by)
    with Tree(d["base"]) as tree:
        before = run_check(tree, run, expect)
        subprocess.run(["git", "-C", str(tree), "apply", str(patch)], check=True)
        after = run_check(tree, run, expect)
    out = {"section": "4bd, positive control (not registered)", "source": source.name, "patch": patch.name,
           "lesson": row["lesson"], "check": run, "before": before, "after": after, "sorted": sort_pair(before, after)}
    print(json.dumps({k: out[k] for k in ("lesson", "check", "sorted")} | {"before": before["why"], "after": after["why"]}))
    if args.receipt:
        write("check-reach-control", guard.stamp(out))
    return 0


# §4be: the rule-wide checks #415 wrote, by the lesson whose rule each sweeps, taken from main at
# SOURCE. Each is (the check file, the pytest selector, or None for a ci/ script).
SOURCE = "8ed0b1d27338874bfd255982827162623883c86f"
RULEWIDE = {
    "n_e7988ff536fb": ("tests/test_exit_codes.py", "not every_command_is_in_the_sweep"),
    "n_5ddb0776a863": ("tests/test_exit_codes.py", "not every_command_is_in_the_sweep"),
    "seed:geospatial-enforcement-defects:r_single_source_sets": ("tests/test_single_source.py", ""),
    "harness-reads-a-moving-working-tree": ("tests/test_eval_guard.py", ""),
    "remote-path-test-through-client": ("tests/test_client_service_contract.py", ""),
    "seed:python-canon:py_dont_mock_what_you_dont_own": ("tests/test_mock_ownership.py", ""),
    "docs-agent-neutral": ("ci/check-agent-neutral.py", None),
    "n_02cc84da158d": ("tests/test_store_resolution.py", ""),
    "n_0637c92c032f": ("ci/check-diagram-names.py", None),
}
RULE_ROWS = lr.PRIVATE / "check-reach-4be.jsonl"


def place_check(tree: Path, path: str) -> str:
    """Copy today's check, and what it leans on, from SOURCE into `tree`; return its command."""
    selector = RULEWIDE_BY_FILE[path]
    helpers = ["tests/conftest.py"] if path.startswith("tests/") else ["ci/_ran.py"]
    for f in [path, *helpers]:
        text = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{f}"], capture_output=True, text=True,
                              check=True).stdout
        (tree / f).parent.mkdir(parents=True, exist_ok=True)
        (tree / f).write_text(text)
    if selector is None:
        return f"python3 {path}"
    return f"python3 -m pytest -q -p no:cacheprovider {path}" + (f" -k '{selector}'" if selector else "")


RULEWIDE_BY_FILE = {f: sel for f, sel in RULEWIDE.values()}


def rule_done() -> dict[tuple[str, int, str], dict]:
    """§4be's rows so far."""
    if not RULE_ROWS.exists():
        return {}
    rows = [json.loads(x) for x in RULE_ROWS.read_text().splitlines() if x.strip()]
    return {(r["half"], r["pr"], r["lesson"]): r for r in rows}


def rulewide(_args: argparse.Namespace) -> int:
    """§4be: each break of a lesson #415 swept, with today's rule-wide check, at the base and the change."""
    at = run_guard.start().started[0]
    have = rule_done()
    todo = [p for p in broken_pairs() if p["lesson"] in RULEWIDE and (p["half"], p["pr"], p["lesson"]) not in have]
    RULE_ROWS.parent.mkdir(parents=True, exist_ok=True)
    by_commit: dict[tuple[str, str], list[dict]] = {}
    for p in todo:
        by_commit.setdefault((p["base"], p["commit"]), []).append(p)
    for (base, commit), group in by_commit.items():
        files = sorted({RULEWIDE[p["lesson"]][0] for p in group})
        results: dict[str, dict] = {}
        for side, sha in (("base", base), ("change", commit)):
            with Tree(sha) as tree:
                for f in files:
                    results.setdefault(f, {})[side] = run_check(tree, place_check(tree, f), None)
        with RULE_ROWS.open("a") as out:
            for p in group:
                f = RULEWIDE[p["lesson"]][0]
                r = results[f]
                row = {**{k: p[k] for k in ("half", "pr", "lesson", "base", "commit")}, "check": f,
                       "at_base": r["base"], "at_change": r["change"], "sorted": sort_pair(r["base"], r["change"]),
                       "okl_commit": at}
                out.write(json.dumps(row) + "\n")
                print(f"#{p['pr']} {p['lesson']} [{f}]: {row['sorted']}", flush=True)
    return 0


def rulewide_score(args: argparse.Namespace) -> int:
    """§4be's measures and reading."""
    guard = run_guard.start()
    covered = [p for p in broken_pairs() if p["lesson"] in RULEWIDE]
    rows = rule_done()
    sorted_ = Counter(r["sorted"] for r in rows.values())
    per_check: dict[str, Counter] = {}
    for r in rows.values():
        per_check.setdefault(r["check"], Counter())[r["sorted"]] += 1
    caught, cannot = sorted_.get("caught", 0), sorted_.get("cannot_judge", 0)
    reading = ("rule-wide checks reach these breaks" if caught >= 10 else
               "the backward method cannot judge today's checks" if cannot > 19 else
               "rule-wide checks do not reach these breaks either")
    receipt = {"section": "4be", "source": SOURCE, "covered": len(covered), "ran": len(rows),
               "sorted": dict(sorted_), "per_check": {k: dict(v) for k, v in per_check.items()},
               "rows_made_at": sorted({r.get("okl_commit") for r in rows.values()} - {None}),
               "cannot_judge_why": dict(Counter(f"base {r['at_base']['why']}; change {r['at_change']['why']}"
                                                for r in rows.values() if r["sorted"] == "cannot_judge")),
               "reading": reading,
               "caught": [{k: r[k] for k in ("half", "pr", "lesson", "check")} for r in rows.values()
                          if r["sorted"] == "caught"]}
    print(json.dumps({k: v for k, v in receipt.items() if k != "caught"}, indent=1))
    if args.receipt:
        write("check-reach-rulewide", guard.stamp(receipt))
    return 0


def write(stem: str, receipt: dict) -> None:
    """Write `receipt` to evals/results/, named by `stem` and the time."""
    receipt["at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    dest = RESULTS / f"{stem}-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"receipt: {dest.relative_to(REPO)}")


def main() -> int:
    """Run the named step."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("count", count), ("pilot", pilot), ("run", run), ("score", score), ("control", control),
                     ("rulewide", rulewide), ("rulewide-score", rulewide_score)):
        s = sub.add_parser(name)
        if name not in ("run", "rulewide"):
            s.add_argument("--receipt", action="store_true")
        s.set_defaults(func=fn)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
