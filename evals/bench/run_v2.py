#!/usr/bin/env python3
"""The prototype decision (evals/bench/v2.py) on the bench: recall at a guaranteed null rate.

    PYTHONPATH=src python3 evals/bench/run_v2.py --label <name> [--triggers evals/bench/triggers.jsonl] \\
        [--split selection] > evals/results/bench-<date>-v2-<name>.txt

The null prompts are split in two by the parity of a hash of their id. The calibration half
sets the line for each alpha (conformal, v2.conformal_line); the other half measures how
often the line briefed a null prompt anything, which is the guarantee checked on prompts the
line never saw. Recall is measured on the queries of the chosen split at each (alpha, cap):
the query's lesson is among the briefed ones. Intervals as in run.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as bench
import v2

ALPHAS = (0.01, 0.05, 0.10)
CAPS = (3, 5, 8)


def main() -> None:
    """Calibrate each line on half the nulls, test it on the other half, and print the grid."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--label", required=True)
    ap.add_argument("--triggers", type=Path)
    ap.add_argument("--split", choices=["selection", "heldout", "all"], default="selection")
    ap.add_argument("--score", choices=sorted(v2.SCORES), default="evidence")
    args = ap.parse_args()
    score = v2.SCORES[args.score]
    queries = [json.loads(x) for x in bench.QUERIES.read_text().splitlines() if x.strip()]
    if args.split != "all":
        queries = [q for q in queries if q["split"] == args.split]
    nulls = [json.loads(x) for x in bench.NULLS.read_text().splitlines() if x.strip()]
    calib = [p for p in nulls if int(hashlib.sha256(p["id"].encode()).hexdigest(), 16) % 2 == 0]
    test = [p for p in nulls if p not in calib]

    with tempfile.TemporaryDirectory() as tmp:
        store = bench.build_corpus(Path(tmp))
        n_trig = bench.load_triggers(store, args.triggers) if args.triggers else 0
        index = v2.build_index(store)
        commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                                cwd=bench.ROOT).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src", "seed", "evals/bench"],
                                    capture_output=True, text=True, cwd=bench.ROOT).stdout.strip())
        lat: list[float] = []

        def run(task: str) -> v2.Decision:
            t0 = time.perf_counter()
            d = v2.decide(store, index, task, line=0.0, cap=10_000, score=score)
            lat.append((time.perf_counter() - t0) * 1000)
            return d

        calib_best = [run(p["text"]).best for p in calib]
        # Every candidate with its score, once per prompt; each (alpha, cap) cell is a filter on it.
        def scored(task: str) -> list[tuple[str, float]]:
            terms = v2.subject(task)
            if v2.from_harness(task) or not terms:
                return []
            found = store.search(" ".join(terms), limit=36)
            out = [(n.id, score(index, terms, n.id)) for n in found]
            return sorted(out, key=lambda t: -t[1])
        q_scored = [(q, scored(q["text"])) for q in queries]
        t_scored = [scored(p["text"]) for p in test]
        for q in queries:
            run(q["text"])

    print(f"bench v2 prototype · label {args.label} · split {args.split} · code {commit}{' (DIRTY)' if dirty else ''}")
    print(f"corpus: {index.n} live records · triggers on {n_trig} lessons"
          f"{f' ({args.triggers.name}, sha {bench.digest([args.triggers])})' if args.triggers else ''} · "
          f"queries sha {bench.digest([bench.QUERIES])} · nulls {len(nulls)} (sha {bench.digest([bench.NULLS])}): "
          f"{len(calib)} calibrate the line, {len(test)} test it")
    print(f"score: {args.score} ({(score.__doc__ or '').split(chr(10))[0].strip()})")
    print()
    print(f"{'alpha':>5} {'line':>6} {'cap':>3} | {'recall [95%]':>22} {'briefed/q':>9} | null test: briefed anything [95%]")
    for alpha in ALPHAS:
        line = v2.conformal_line(calib_best, alpha)
        for cap in CAPS:
            by_lesson: dict[str, list[float]] = defaultdict(list)
            counts = []
            for q, sc in q_scored:
                ids = [nid for nid, s in sc if s >= line][:cap]
                by_lesson[q["lesson"]].append(1.0 if q["lesson"] in ids else 0.0)
                counts.append(len(ids))
            m, lo, hi = bench.boot_ci(by_lesson)
            hit = sum(1 for sc in t_scored if sc and sc[0][1] >= line)
            wlo, whi = bench.wilson(hit, len(t_scored))
            print(f"{alpha:>5} {line:>6.3f} {cap:>3} | {m:>7.1%} [{lo:5.1%}, {hi:5.1%}] {statistics.mean(counts):>9.2f} | "
                  f"{hit} of {len(t_scored)} ({hit / len(t_scored):.1%}, [{wlo:.1%}, {whi:.1%}])")
    by_reg: dict[str, list[int]] = defaultdict(list)
    line = v2.conformal_line(calib_best, 0.05)
    for q, sc in q_scored:
        ids = [nid for nid, s in sc if s >= line][:5]
        by_reg[q["register"]].append(1 if q["lesson"] in ids else 0)
    print("\nat alpha 0.05, cap 5, by register: " + " · ".join(f"{r} {sum(v)}/{len(v)}" for r, v in sorted(by_reg.items())))
    lat.sort()
    print(f"latency per decision: median {statistics.median(lat):.1f} ms · p95 {lat[int(0.95 * (len(lat) - 1))]:.1f} ms")


if __name__ == "__main__":
    main()
