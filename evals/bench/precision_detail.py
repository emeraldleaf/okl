#!/usr/bin/env python3
"""Exploratory detail beside the judged-precision receipt: what each arm missed, and how much the judge moves it (#291).

    PYTHONPATH=src python3 evals/bench/precision_detail.py \\
        --alt evals/bench/private/judge-out-3-listdefault.jsonl > evals/results/bench-<date>-precision-detail.txt

Not pre-registered (§4w registered precision only); written after the tally was read, and
said so wherever it is quoted. It reads the same private files as `precision_pairs.py tally`.
The lessons judged to apply are known only among those either arm briefed, so "no lesson
applies" below means none that either arm found, not none in the corpus.

Per arm: the prompts where it briefed a lesson that applies; the prompts where some lesson
applies (by either arm) and it briefed none of them; how many of its silent prompts had an
applying lesson the other arm found; and the lessons that do not apply, per prompt. With
--alt, a second labelling of some pairs (a re-judged batch): agreement and Cohen's kappa
between the two on those pairs, and each arm's precision with the alternative labels in place.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import precision_pairs as pp

LABELS = ("APPLIES", "DOES_NOT_APPLY", "UNSURE")


def read_labels(path: Path) -> dict[int, str]:
    """Pair index -> label, from a judge's JSONL output."""
    return {int(o["pair"]): o["label"] for o in (json.loads(x) for x in path.read_text().splitlines() if x.strip())}


def kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa for two labellings of the same items."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in LABELS) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def precision(arms: dict, pair_label: dict) -> dict[str, tuple[int, int]]:
    """Per arm: (judged APPLIES, judged APPLIES or DOES_NOT_APPLY) over the lessons it briefed."""
    out = {}
    for arm, by_prompt in arms.items():
        labels = [pair_label.get((pid, lid)) for pid, ids in by_prompt.items() for lid in ids]
        out[arm] = (labels.count("APPLIES"), sum(1 for v in labels if v in ("APPLIES", "DOES_NOT_APPLY")))
    return out


def main() -> None:
    """Print what each arm missed on real prompts, and the judge's sensitivity."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--alt", type=Path, help="a second labelling of some pairs, to measure the judge")
    args = ap.parse_args()
    meta = json.loads(pp.ARMS_FILE.read_text())
    labels = read_labels(pp.JUDGE_OUT)
    pairs = [tuple(x) for x in meta["pairs"]]
    pair_label = {pr: labels.get(i) for i, pr in enumerate(pairs)}
    arms = meta["arms"]
    prompts = meta["sample"]
    applies = {pid: {lid for (p, lid), v in pair_label.items() if p == pid and v == "APPLIES"} for pid in prompts}
    with_any = [pid for pid in prompts if applies[pid]]
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=pp.bench.ROOT, check=False).stdout.strip()
    print(f"bench judged precision, detail (exploratory, not pre-registered) · {len(prompts)} real TASK prompts · "
          f"{len(pairs)} pairs · code {commit}")
    print(f"prompts where a lesson either arm briefed was judged to apply: {len(with_any)} of {len(prompts)}\n")
    for arm, by_prompt in arms.items():
        hit = [pid for pid in with_any if applies[pid] & set(by_prompt.get(pid, []))]
        silent = [pid for pid in prompts if not by_prompt.get(pid)]
        silent_missed = [pid for pid in silent if applies[pid]]
        wrong = sum(1 for pid, ids in by_prompt.items() for lid in ids if pair_label.get((pid, lid)) == "DOES_NOT_APPLY")
        found = sum(len(applies[pid] & set(by_prompt.get(pid, []))) for pid in prompts)
        total = sum(len(applies[pid]) for pid in prompts)
        print(f"{arm:9} briefed an applying lesson on {len(hit)} of those {len(with_any)} prompts · "
              f"found {found} of the {total} applying lessons either arm found · silent on {len(silent)} prompts, "
              f"{len(silent_missed)} of them with an applying lesson the other arm found · "
              f"{wrong / len(prompts):.1f} lessons that do not apply, per prompt")
    if args.alt:
        alt = read_labels(args.alt)
        common = sorted(set(alt) & set(labels))
        a, b = [labels[i] for i in common], [alt[i] for i in common]
        agree = sum(x == y for x, y in zip(a, b, strict=True))
        print(f"\nsecond labelling ({args.alt.name}) of {len(common)} pairs: agree on {agree} "
              f"({agree / len(common):.1%}) · Cohen's kappa {kappa(a, b):.2f} · APPLIES {a.count('APPLIES')} here, "
              f"{b.count('APPLIES')} there")
        swapped = {pr: (alt[i] if i in alt else labels.get(i)) for i, pr in enumerate(pairs)}
        for arm, (yes, judged) in precision(arms, swapped).items():
            print(f"  {arm:9} precision with the second labelling in place: {yes} of {judged} ({yes / judged:.1%})")


if __name__ == "__main__":
    main()
