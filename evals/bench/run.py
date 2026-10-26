#!/usr/bin/env python3
"""The retrieval benchmark: one arm of okl's briefing against the bench's queries.

    PYTHONPATH=src python3 evals/bench/run.py --label fulltext [--hybrid linear] [--rerank] \\
        [--split selection|heldout|all] > evals/results/bench-<date>-<label>.txt

The corpus is the twelve committed seed packs, imported into a fresh store on every run, so the
receipt depends only on committed inputs and the code at its commit. The queries
(evals/bench/queries.jsonl) carry the lesson each one should brief, its register (ticket,
paraphrase, bug report) and its split. The selection split is for choosing; the held-out split
is run once per pre-registered decision. The null prompts are real prompts a person typed that
should brief nothing (evals/bench/private/null_prompts.jsonl, built on the machine that holds
the sessions and never committed); the receipt carries their count, a hash of the set, and how
many of them were briefed anything, never their text.

Reported per register: recall after the floor (the lesson is in the briefing), the lesson's rank
in check's own candidate order before the floor (hit@1, hit@3, hit@12, MRR), and the mean number
of lessons briefed; for the null prompts, how many were briefed nothing and how many lessons the
rest received; median and 95th-percentile latency. Intervals are 95% percentile bootstraps
that resample lessons, not queries, because the registers of one lesson are not independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from okl import core  # noqa: E402
from okl.client import Client  # noqa: E402
from okl.seed import seed_from_file  # noqa: E402
from okl.store import Store  # noqa: E402

QUERIES = ROOT / "evals" / "bench" / "queries.jsonl"
NULLS = ROOT / "evals" / "bench" / "private" / "null_prompts.jsonl"
REPO = "bench"
BOOT = 2000


def is_calibration(prompt: dict) -> bool:
    """Whether a null prompt is in the half that sets lines (even SHA-256 parity of its id); the
    other half tests them. One rule for every runner, so none calibrates on prompts another
    treats as unseen."""
    return int(hashlib.sha256(prompt["id"].encode()).hexdigest(), 16) % 2 == 0


def build_corpus(where: Path) -> Store:
    """A store holding every seed pack, built in `where`, without triggers.

    The packs carry the bench's triggers since §4w passed; every receipt before that ran on
    packs without them. Dropping them here keeps each arm's meaning fixed: an arm has
    triggers only when it loads them (load_triggers, --triggers)."""
    import dataclasses
    (where / ".okl").mkdir(parents=True, exist_ok=True)
    (where / ".okl" / "config.json").write_text(json.dumps({"repo": REPO}))
    here = Path.cwd()
    os.chdir(where)
    try:
        client = Client()
        for pack in sorted((ROOT / "seed").glob("*.json")):
            seed_from_file(client, str(pack))
        store = client._local_store()
        for node in store.all_nodes():
            if node.triggers:
                store.add_node(dataclasses.replace(node, triggers=None))
        return store
    finally:
        os.chdir(here)


def load_triggers(store: Store, path: Path) -> int:
    """Write the bench's generated triggers onto the corpus's lessons; returns how many lessons."""
    import dataclasses
    by_lesson: dict[str, list[str]] = defaultdict(list)
    for line in path.read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            by_lesson[t["lesson"]].append(t["text"].strip())
    for lesson, texts in by_lesson.items():
        node = store.get_node(lesson)
        if node is None:
            sys.exit(f"triggers: no lesson {lesson} in the corpus")
        store.add_node(dataclasses.replace(node, triggers="\n".join(texts)))
    return len(by_lesson)


def digest(paths: list[Path]) -> str:
    """A short hash of the files' bytes, so a receipt names exactly what it ran on."""
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def repo_for(store: Store, lesson: str) -> str:
    """The repo a query about `lesson` is asked from: the lesson's own repo when it is
    repo-scoped (a seed pack keeps eighteen lessons to the project they came from, and check
    rightly shows them nowhere else), the bench's repo otherwise."""
    node = store.get_node(lesson)
    return node.scope[len("repo:"):] if node and node.scope.startswith("repo:") else REPO


def rank_of(store: Store, task: str, nid: str, *, repo: str, hybrid: str | None, rerank: bool,
            n_all: int) -> int | None:
    """The lesson's position in check's candidate order, in scope and live (the probe's rule)."""
    found = core.ranked_candidates(store, task, n_all, hybrid).nodes
    if rerank:
        window = core.ranked_candidates(store, task, 36, hybrid, rerank=True).nodes
        seen = {n.id for n in window}
        found = window + [n for n in found if n.id not in seen]
    ids = [n.id for n in found if core._in_scope(n, f"repo:{repo}", None) and n.status not in core.RETIRED_STATUSES]
    return ids.index(nid) + 1 if nid in ids else None


def boot_ci(per_lesson: dict[str, list[float]], seed: int = 7) -> tuple[float, float, float]:
    """Mean over queries and its 95% interval, resampling lessons."""
    lessons = list(per_lesson)
    flat = [v for vs in per_lesson.values() for v in vs]
    rng = random.Random(seed)  # noqa: S311 - a seeded bootstrap, reproducible on purpose
    means = []
    for _ in range(BOOT):
        sample = [v for lesson in rng.choices(lessons, k=len(lessons)) for v in per_lesson[lesson]]  # NOSONAR - seeded
        means.append(sum(sample) / len(sample))
    means.sort()
    return sum(flat) / len(flat), means[int(0.025 * BOOT)], means[int(0.975 * BOOT) - 1]


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def main() -> None:
    """Run one arm over the chosen split and the null prompts, and print the receipt."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--label", required=True)
    ap.add_argument("--hybrid", choices=["off", "linear", "rrf"], default="off")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--split", choices=["selection", "heldout", "all"], default="selection")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--queries", type=Path, default=QUERIES)
    ap.add_argument("--triggers", type=Path, help="load write-time triggers onto the corpus first")
    ap.add_argument("--decision", choices=["floor", "calibrated"], default="floor",
                    help="core.check's decision: the word floor, or the calibrated line (#291)")
    args = ap.parse_args()
    hybrid = None if args.hybrid == "off" else args.hybrid

    queries = [json.loads(line) for line in args.queries.read_text().splitlines() if line.strip()]
    if args.split != "all":
        queries = [q for q in queries if q["split"] == args.split]
    nulls = [json.loads(line) for line in NULLS.read_text().splitlines() if line.strip()] if NULLS.exists() else []

    with tempfile.TemporaryDirectory() as tmp:
        store = build_corpus(Path(tmp))
        n_trig = load_triggers(store, args.triggers) if args.triggers else 0
        n_all = len(store.all_nodes())
        if hybrid or args.rerank:
            from okl import semantic
            semantic.build_index(store, offline=True)
        commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                                cwd=ROOT).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src", "seed", "evals/bench"],
                                    capture_output=True, text=True, cwd=ROOT).stdout.strip())

        rows, latencies = [], []
        for q in queries:
            t0 = time.perf_counter()
            repo = repo_for(store, q["lesson"])
            res = core.check(store, repo=repo, task=q["text"], interests=None, limit=args.limit,
                             hybrid=hybrid, rerank=args.rerank, decision=args.decision)
            latencies.append((time.perf_counter() - t0) * 1000)
            if hybrid and res.get("hybrid_unavailable"):
                sys.exit(f"bench: {res['hybrid_unavailable']}")
            if args.rerank and res.get("rerank_unavailable"):
                sys.exit(f"bench: {res['rerank_unavailable']}")
            briefed = core.briefed_ids(res)
            rk = rank_of(store, q["text"], q["lesson"], repo=repo, hybrid=hybrid, rerank=args.rerank, n_all=n_all)
            rows.append({**q, "briefed": q["lesson"] in briefed, "rank": rk, "count": len(briefed)})
        null_counts, null_half = [], []
        for p in nulls:
            t0 = time.perf_counter()
            res = core.check(store, repo=REPO, task=p["text"], interests=None, limit=args.limit,
                             hybrid=hybrid, rerank=args.rerank, decision=args.decision)
            latencies.append((time.perf_counter() - t0) * 1000)
            null_counts.append(len(core.briefed_ids(res)))
            # The half that set decide.CALIBRATED_LINE (even hash parity) and the half that did not.
            null_half.append("calibration" if is_calibration(p) else "unseen")

    print(f"bench · label {args.label} · split {args.split} · code {commit}{' (DIRTY: uncommitted src/seed/bench changes)' if dirty else ''}")
    print(f"corpus: {n_all} records from {len(list((ROOT / 'seed').glob('*.json')))} seed packs (sha {digest(sorted((ROOT / 'seed').glob('*.json')))}) · "
          f"queries {args.queries.name} sha {digest([args.queries])} · nulls {len(nulls)} (sha {digest([NULLS]) if NULLS.exists() else '-'})")
    print(f"arm: decision {args.decision} · hybrid {args.hybrid} · rerank {'on' if args.rerank else 'off'} · limit {args.limit} · "
          f"common-word share {core.COMMON_WORD_SHARE} · interests none · triggers on {n_trig} lessons"
          + (f" ({args.triggers.name}, sha {digest([args.triggers])})" if args.triggers else ""))
    print()
    print(f"{'register':11} {'n':>4} {'recall (briefed)':>24} {'hit@1':>6} {'hit@3':>6} {'hit@12':>7} {'MRR':>6} {'briefed/q':>9}")
    registers = sorted({r["register"] for r in rows}) + ["all"]
    for reg in registers:
        sub = [r for r in rows if reg == "all" or r["register"] == reg]
        if not sub:
            continue
        by_lesson: dict[str, list[float]] = defaultdict(list)
        for r in sub:
            by_lesson[r["lesson"]].append(1.0 if r["briefed"] else 0.0)
        m, lo, hi = boot_ci(by_lesson)
        hit = {k: sum(1 for r in sub if r["rank"] and r["rank"] <= k) / len(sub) for k in (1, 3, 12)}
        mrr = sum(1 / r["rank"] for r in sub if r["rank"]) / len(sub)
        mean_count = sum(r["count"] for r in sub) / len(sub)
        print(f"{reg:11} {len(sub):>4} {m:>8.1%} [{lo:5.1%}, {hi:5.1%}] {hit[1]:>6.1%} {hit[3]:>6.1%} {hit[12]:>7.1%} "
              f"{mrr:>6.3f} {mean_count:>9.1f}")
    if null_counts:
        quiet = sum(1 for c in null_counts if c == 0)
        lo, hi = wilson(quiet, len(null_counts))
        given = [c for c in null_counts if c]
        print(f"\nnull prompts briefed nothing: {quiet} of {len(null_counts)} ({quiet / len(null_counts):.1%}, 95% "
              f"[{lo:.1%}, {hi:.1%}]) · the rest got {statistics.mean(given) if given else 0:.1f} lessons on average")
        for half in ("calibration", "unseen"):
            sub = [c for c, h in zip(null_counts, null_half, strict=True) if h == half]
            hit = sum(1 for c in sub if c)
            hlo, hhi = wilson(hit, len(sub))
            role = "sets the calibrated line" if half == "calibration" else "never seen by the calibrated line"
            print(f"  {half} half ({role}): "
                  f"briefed anything {hit} of {len(sub)} ({hit / len(sub):.1%}, 95% [{hlo:.1%}, {hhi:.1%}])")
    else:
        print("\nnull prompts: none on this machine (evals/bench/private/null_prompts.jsonl absent)")
    lat = sorted(latencies)
    print(f"latency per check: median {statistics.median(lat):.0f} ms · p95 {lat[int(0.95 * (len(lat) - 1))]:.0f} ms · "
          f"{len(lat)} checks")
    print("\nper query: id register lesson rank briefed count")
    for r in rows:
        print(f"{r['id']} {r['register']} {r['lesson']} {r['rank'] or '-'} {'yes' if r['briefed'] else 'MISS'} {r['count']}")


if __name__ == "__main__":
    main()
