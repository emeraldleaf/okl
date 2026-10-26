#!/usr/bin/env python3
"""Judged precision on real task prompts: is each lesson a decision briefs one that applies? (#291)

    PYTHONPATH=src python3 evals/bench/precision_pairs.py pairs --sample 100 --seed 7
    # a judge (a model other than the one that wrote the triggers) labels private/judge-in.jsonl
    PYTHONPATH=src python3 evals/bench/precision_pairs.py tally > evals/results/bench-<date>-precision.txt

The bench's queries were written by one model and its triggers by another of the same family,
which can flatter the trigger arm on synthetic queries (CIKM 2025, arXiv 2506.10301). Real
prompts are the check: a seeded sample of the prompts labelled TASK (a person typed them, and
they name a subject of their own) is briefed by the control (`--decision floor`, no triggers,
today's default) and the treatment (`--decision calibrated` with triggers), each prompt from
the bench's repo against the seed corpus. Every (prompt, lesson) pair either arm briefed goes
to the judge once, shuffled, with no mark of which arm briefed it. The tally reports, per arm,
the share of its briefed lessons the judge said apply, the prompts it briefed anything, and
lessons per prompt; and the lessons that apply which only one arm briefed. The prompts stay on
the machine that holds them: the files are under private/, and the receipt carries counts.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as bench

from okl import core

PRIVATE = bench.ROOT / "evals" / "bench" / "private"
TASKS = PRIVATE / "task_prompts.jsonl"
JUDGE_IN = PRIVATE / "judge-in.jsonl"
JUDGE_OUT = PRIVATE / "judge-out.jsonl"
ARMS_FILE = PRIVATE / "judge-arms.json"


def make_pairs(sample: int, seed: int) -> None:
    """Brief the sampled prompts under both arms and write the blind, shuffled judging file."""
    prompts = [json.loads(x) for x in TASKS.read_text().splitlines() if x.strip()]
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not a secret
    chosen = rng.sample(prompts, min(sample, len(prompts)))
    arms: dict[str, dict[str, list[str]]] = {"control": {}, "treatment": {}}
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        plain = bench.build_corpus(Path(a))
        expanded = bench.build_corpus(Path(b))
        bench.load_triggers(expanded, bench.ROOT / "evals" / "bench" / "triggers.jsonl")
        lessons = {n.id: n for n in plain.all_nodes()}
        for p in chosen:
            arms["control"][p["id"]] = core.briefed_ids(core.check(plain, repo=bench.REPO, task=p["text"],
                                                                   interests=None, decision="floor"))
            arms["treatment"][p["id"]] = core.briefed_ids(core.check(expanded, repo=bench.REPO, task=p["text"],
                                                                     interests=None, decision="calibrated"))
    pairs = sorted({(pid, lid) for arm in arms.values() for pid, ids in arm.items() for lid in ids})
    rng.shuffle(pairs)
    text = {p["id"]: p["text"] for p in chosen}
    with JUDGE_IN.open("w") as f:
        for i, (pid, lid) in enumerate(pairs):
            n = lessons[lid]
            f.write(json.dumps({"pair": i, "prompt": text[pid], "lesson_title": n.title,
                                "lesson_symptom": n.symptom or "", "lesson_fix": n.fix or ""}) + "\n")
    ARMS_FILE.write_text(json.dumps({"seed": seed, "sample": [p["id"] for p in chosen], "arms": arms,
                                     "pairs": [[pid, lid] for pid, lid in pairs]}))
    print(f"{len(chosen)} prompts · {len(pairs)} pairs to judge -> {JUDGE_IN}", file=sys.stderr)


def tally() -> None:
    """Join the judge's labels back to the arms and print the receipt."""
    meta = json.loads(ARMS_FILE.read_text())
    labels = {int(o["pair"]): o["label"] for o in (json.loads(x) for x in JUDGE_OUT.read_text().splitlines()
                                                     if x.strip())}
    pair_label = {(pid, lid): labels.get(i) for i, (pid, lid) in enumerate(meta["pairs"])}
    missing = sum(1 for v in pair_label.values() if v is None)
    print(f"bench judged precision · {len(meta['sample'])} real TASK prompts (seed {meta['seed']}) · "
          f"{len(meta['pairs'])} pairs · judge labels missing: {missing}")
    print("control: --decision floor, no triggers (today's default) · treatment: --decision calibrated, triggers")
    print()
    applies_only: dict[str, int] = defaultdict(int)
    for arm, by_prompt in meta["arms"].items():
        briefed = [(pid, lid) for pid, ids in by_prompt.items() for lid in ids]
        judged = [pair_label[x] for x in briefed if pair_label.get(x) in ("APPLIES", "DOES_NOT_APPLY")]
        yes = sum(1 for v in judged if v == "APPLIES")
        lo, hi = bench.wilson(yes, len(judged))
        any_b = sum(1 for ids in by_prompt.values() if ids)
        print(f"{arm:9} briefed {len(briefed):4} lessons on {any_b:3} of {len(by_prompt)} prompts "
              f"({len(briefed) / len(by_prompt):.1f} a prompt) · judged apply {yes} of {len(judged)} "
              f"({yes / len(judged) if judged else 0:.1%}, 95% [{lo:.1%}, {hi:.1%}]) · unsure "
              f"{sum(1 for x in briefed if pair_label.get(x) == 'UNSURE')}")
        other = "treatment" if arm == "control" else "control"
        for pid, lid in briefed:
            if pair_label.get((pid, lid)) == "APPLIES" and lid not in meta["arms"][other].get(pid, []):
                applies_only[arm] += 1
    print(f"\nlessons judged to apply that only one arm briefed: control {applies_only['control']}, "
          f"treatment {applies_only['treatment']}")


def main() -> None:
    """Make the judging pairs, or tally the judge's labels."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pairs")
    pp.add_argument("--sample", type=int, default=100)
    pp.add_argument("--seed", type=int, default=7)
    sub.add_parser("tally")
    args = ap.parse_args()
    if args.cmd == "pairs":
        make_pairs(args.sample, args.seed)
    else:
        tally()


if __name__ == "__main__":
    main()
