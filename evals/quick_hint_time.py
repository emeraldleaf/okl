#!/usr/bin/env python3
"""What the quick hint costs (#470), timed as `okl init` works it out.

While no check is approved, `okl on-edit` and `okl init` say how many lesson checks are quick. That
reads every lesson, then each one's check log once, on a local store only. This times it on a copy
of okl's own store and on made-up stores of 1,000 and 5,000 lessons whose checks all carry a timed
run, so the receipt shows how the cost grows. Sizes and milliseconds only; no lesson text.

    python3 evals/quick_hint_time.py [--receipt]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr
import run_guard
import sandbox as sb

REPEATS = 7
MADE_UP = (1000, 5000)


@contextlib.contextmanager
def _store_at(url: str):
    """Point okl at `url` for this process only, as OKL_DATABASE_URL would; restored after."""
    before = os.environ.get("OKL_DATABASE_URL")
    os.environ["OKL_DATABASE_URL"] = url
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("OKL_DATABASE_URL", None)
        else:
            os.environ["OKL_DATABASE_URL"] = before


def _time_hint() -> dict:
    """The hint as `okl init` works it out (it loads the lessons itself), timed REPEATS times."""
    from okl.cli import on_edit
    from okl.client import Client
    client = Client()
    nodes = {n.id: n for n in client.all_nodes()}
    addable = len(on_edit._addable({}, nodes, client.repo))
    took = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        on_edit.quick_hint(Client(), {})
        took.append((time.perf_counter() - start) * 1000)
    return {"lessons": len(nodes), "could_run_on_edit": addable,
            "median_ms": round(statistics.median(took), 1), "max_ms": round(max(took), 1)}


def _made_up(path: Path, n: int) -> None:
    """A store of `n` lessons, each with a stored check and one timed passing run of it."""
    from okl import core
    from okl.store import Store
    store = Store(f"sqlite:///{path}")
    try:
        for i in range(n):
            lid = f"l{i:05d}"
            core.record(store, id=lid, type="Rule", title=f"lesson {i}", scope="org")
            core.verify(store, lid, f"`true {i}` exit 0 @ 2026-11-15T00:00Z")
            core.log_check(store, lid, passed=True, command=f"true {i}", outcome="exit 0", seconds=0.2)
    finally:
        store.close()


def main() -> int:
    """Time the hint on each store; write the receipt with --receipt."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    guard = run_guard.start()
    rows = {}
    with tempfile.TemporaryDirectory() as d:
        own = Path(d) / "own.db"
        sb.copy_sqlite(dr.main_store(), own)
        with _store_at(f"sqlite:///{own}"):
            rows["okl's own store"] = _time_hint()
        for n in MADE_UP:
            made = Path(d) / f"made-{n}.db"
            _made_up(made, n)
            with _store_at(f"sqlite:///{made}"):
                rows[f"made up, {n:,} lessons"] = _time_hint()
    out = guard.stamp({"what": "the quick hint's cost, as okl init works it out (#470)", "repeats": REPEATS,
                       "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "stores": rows})
    print(json.dumps(out["stores"], indent=1))
    if args.receipt:
        dest = dr.RESULTS / f"quick-hint-time-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(dr.REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
