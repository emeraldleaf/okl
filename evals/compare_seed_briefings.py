#!/usr/bin/env python3
"""Compare the eval tasks' briefings between two seed trees: a git ref's packs and the working tree's.

    python3 evals/compare_seed_briefings.py [--against origin/main] [--interests "a,b"]

Seeds two throwaway stores, one from each tree, and prints per task whether the governing
record is briefed on each side, the ids that left and arrived, the recall of the held-out
rephrasings (evals/heldout_variants.json) on each side, and how many records the six short
precision prompts (evals/probe_prompts.json) return on each side. A deterministic pre-flight
for a seed-content change (REPORT §4p): whether a record reaches a briefing is a query,
answered in seconds, not a model call.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from okl import core
from okl.store import Store

REPO = Path(__file__).resolve().parent.parent
BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones",
           "threat_prior_art", "vocabulary", "decisions", "context")


def _seeded(seed_dir: Path, db: Path) -> Store:
    """A store seeded from every pack in `seed_dir`, at `db` (this process's env only).

    The client is built from an explicit config with no service URL, and the variable that
    would select a shared service is dropped for this process: with either set, Client()
    goes remote and the seeds would be written to the live service, not the throwaway store
    (review on #266).
    """
    from okl.client import Client
    from okl.seed import seed_from_file
    os.environ.pop("OKL_SERVICE_URL", None)
    os.environ["OKL_DATABASE_URL"] = f"sqlite:///{db}"
    client = Client(config={"repo": "okl"})
    if client.mode != "local":
        raise SystemExit("ABORT: the comparison must write to throwaway stores, and this client is remote")
    for pack in sorted(seed_dir.glob("*.json")):
        seed_from_file(client, str(pack))
    return client._local_store()


def _ids(store: Store, task: str, interests: list[str] | None) -> list[str]:
    res = core.check(store, repo="okl", task=task, interests=interests)
    return [r["id"] for b in BUCKETS for r in res.get(b, [])]


def main() -> int:
    """Seed both trees, compare the eight briefings and the held-out recall, print the table."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", default="origin/main", help="git ref whose seed/ is the baseline")
    ap.add_argument("--interests", default="", help="comma-separated interests; empty = unfiltered, as the harness")
    a = ap.parse_args()
    interests = [t.strip().lower() for t in a.interests.split(",") if t.strip()] or None
    tasks = [json.loads(line) for line in (REPO / "evals" / "tasks.jsonl").read_text().splitlines() if line.strip()]
    heldout = json.loads((REPO / "evals" / "heldout_variants.json").read_text())
    prompts = json.loads((REPO / "evals" / "probe_prompts.json").read_text())["prompts"]
    with tempfile.TemporaryDirectory(prefix="okl-seed-compare-") as tmp:
        base = Path(tmp) / "base"; base.mkdir()
        names = subprocess.run(["git", "-C", str(REPO), "ls-tree", "--name-only", a.against, "seed/"],
                               capture_output=True, text=True, check=True).stdout.split()
        for name in names:
            if name.endswith(".json"):
                (base / Path(name).name).write_text(subprocess.run(
                    ["git", "-C", str(REPO), "show", f"{a.against}:{name}"],
                    capture_output=True, text=True, check=True).stdout)
        before = _seeded(base, Path(tmp) / "before.db")
        after = _seeded(REPO / "seed", Path(tmp) / "after.db")
        print(f"briefings: seed/ at {a.against} vs the working tree · interests={interests or 'none'}")
        for t in tasks:
            x, y = _ids(before, t["task"], interests), _ids(after, t["task"], interests)
            gov = t["defect_node"]
            print(f"  {t['id']:16} governing {'kept' if gov in y else 'LOST' if gov in x else 'absent on both sides'}"
                  f"  left={[i.split(':')[-1] for i in x if i not in y]}  arrived={[i.split(':')[-1] for i in y if i not in x]}")
        print("held-out recall (of 8), before -> after:")
        for label in ("ticket", "paraphrase", "bug-report"):
            b = sum(t["defect_node"] in _ids(before, heldout[t["id"]][label], interests) for t in tasks)
            c = sum(t["defect_node"] in _ids(after, heldout[t["id"]][label], interests) for t in tasks)
            print(f"  {label:11} {b} -> {c}")
        print("records returned to the six precision prompts, before -> after:")
        for p in prompts:
            print(f"  {len(_ids(before, p, interests)):2} -> {len(_ids(after, p, interests)):2}  {p!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
