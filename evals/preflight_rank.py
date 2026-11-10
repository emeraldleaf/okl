#!/usr/bin/env python3
"""Why a pre-flight task lost its rule: where the rule ranks, how many places the briefing has,
what ranks ahead of it that was recorded since a date, and whether older code misses it too.

The receipt behind REPORT §4aa's dated note of 2026-11-10 (ci_linter). Older code is run against
a copy of the store, never the live one (lesson dev-code-migrates-live-store).

    python3 evals/preflight_rank.py ci_linter --since 2026-10-31T02:00Z --also-at f585f1c --receipt
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import run_guard

from okl import core
from okl.client import Client

REPO = Path(__file__).resolve().parents[1]
FULL_BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones",
                "threat_prior_art", "vocabulary")
WIDE = 40   # a limit wide enough to see where a rule lands past the briefing's own


def rank(task_id: str, since_ms: float) -> dict:
    """The rule's place under the default briefing and under a wide one, and who is ahead of it."""
    task = next(json.loads(line) for line in (REPO / "evals" / "tasks.jsonl").read_text().splitlines()
                if line.strip() and json.loads(line)["id"] == task_id)
    store = Client()._local_store()
    rule = task["defect_node"]

    def order(limit: int) -> tuple[list[str], int]:
        res = core.check(store, repo="okl", task=task["task"], interests=None, limit=limit)
        full = [r["id"] for b in FULL_BUCKETS for r in res.get(b, [])]
        return full + [e["id"] for e in res.get("also_matched") or []], len(full)

    default, full_default = order(12)
    wide, _ = order(WIDE)
    ahead = wide[: wide.index(rule)] if rule in wide else wide
    return {"task": task_id, "rule": rule, "places_by_default": len(default), "shown_in_full_by_default": full_default,
            "in_default_briefing": rule in default, "position_at_wide_limit": wide.index(rule) + 1 if rule in wide else None,
            "wide_limit": WIDE, "store_records": len(store.all_nodes()),
            "ahead_recorded_since": [i for i in ahead if (store.get_node(i).created_at or 0) > since_ms]}


def older_code(commit: str) -> dict:
    """The pre-flight of `commit`'s code against a copy of today's store."""
    live = Path((Client()._local_store().url or "").removeprefix("sqlite:///"))
    with tempfile.TemporaryDirectory(prefix="okl-rank-") as tmp:
        copy = Path(tmp) / "okl.db"
        src = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        dst = sqlite3.connect(copy)
        src.backup(dst)
        src.close(); dst.close()
        wt = Path(tmp) / "wt"
        subprocess.run(["git", "-C", str(REPO), "worktree", "add", "-q", "--detach", str(wt), commit], check=True)
        try:
            env = {**os.environ, "PYTHONPATH": str(wt / "src"), "OKL_BRIEFING_LOG": "0",
                   "OKL_DATABASE_URL": f"sqlite:///{copy}"}
            p = subprocess.run([sys.executable, "evals/preflight.py"], cwd=wt, env=env, capture_output=True, text=True)
        finally:
            subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)], check=False)
    return {"commit": commit, "exit": p.returncode, "missing_lines": [ln.strip() for ln in p.stdout.splitlines() if "MISSING" in ln]}


def main() -> int:
    """Rank one task's rule, optionally against older code too, and write a receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--since", required=True, help="UTC time, as 2026-10-31T02:00Z")
    ap.add_argument("--also-at", dest="also_at", help="a commit whose pre-flight to run on a copy of today's store")
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    run = run_guard.start()
    since = datetime.strptime(a.since, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    out = {"section": "4aa dated note", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "since": a.since,
           "now": rank(a.task, since.timestamp() * 1000)}
    if a.also_at:
        out["older_code"] = older_code(a.also_at)
    out = run.stamp(out)
    print(json.dumps(out, indent=1))
    if a.receipt:
        dest = REPO / "evals" / "results" / f"preflight-rank-{a.task}-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
