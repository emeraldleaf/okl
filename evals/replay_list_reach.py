#!/usr/bin/env python3
"""REPORT §4ax's amendment: on §4aw's five tasks, does the default briefing show the right lesson?

The ranks first quoted came from the search with linear fusion, before the briefing's own filters.
This runs `core.check` as a briefing does, from each task's words, on the lessons as they stood.

    python3 evals/replay_list_reach.py [--receipt]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import explain_search as es
import run_guard

from okl import core, decide
from okl.cli.lessons import _BRIEFED_BUCKETS
from okl.store import Store

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "evals" / "replay-tasks-4aw.json"
INTERESTS = ["python", "method", "ci", "security"]   # okl's own declared stack, as its config holds them
HALF = {"4al": "dev", "4aq": "test"}


def reach(task: dict, interests: list[str]) -> dict:
    """Where the right lesson lands in a default briefing from the task's words."""
    frozen = {x["pr"]: x for x in es.tasks_of(HALF[task["set"]])}[task["pr"]]
    words = " ".join([task["title"], *(f"{i['title']} {i['body']}" for i in task["issues"])])
    with tempfile.TemporaryDirectory() as side:
        store = Store(f"sqlite:///{es.store_for(HALF[task['set']], frozen, Path(side))}")
        res = core.check(store, "okl", words, interests=interests, limit=12, decision=decide.DEFAULT)
    full = [r["id"] for b in _BRIEFED_BUCKETS for r in res.get(b, [])]
    named = [e["id"] for e in res.get("also_matched") or []]
    where = "in full" if task["lesson"] in full else "named in one line" if task["lesson"] in named else "not shown"
    return {"pr": task["pr"], "lesson": task["lesson"], "where": where, "in_full": len(full), "named": len(named)}


def main() -> int:
    """Report each task's reach, and write a receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    a = ap.parse_args()
    run = run_guard.start()
    config = json.loads((REPO / ".okl" / "config.json").read_text())
    interests = config.get("interests") or INTERESTS
    rows = [reach(t, interests) for t in json.loads(TASKS.read_text())]
    out = run.stamp({"section": "4ax amendment", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "decision": decide.DEFAULT,
                     "interests": interests, "shown": sum(r["where"] != "not shown" for r in rows), "of": len(rows), "tasks": rows})
    print(json.dumps(out, indent=1))
    if a.receipt:
        a.receipt.write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
