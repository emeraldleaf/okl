#!/usr/bin/env python3
"""Check the generated trigger batches and write evals/bench/triggers.jsonl.

    python3 evals/bench/assemble_triggers.py <dir holding triggers-*.jsonl> --generator <model>

Triggers are a write-time expansion of each seed lesson: ten phrasings of the moments it
applies (4 task, 3 symptom, 3 vocabulary), written from the lesson alone by a model other
than the one that wrote the bench's queries, which its writers never saw. Checked here: every
advice lesson has ten, in those kinds, each 5 to 25 words. Reported, not enforced: how much the
triggers share with the bench's queries for the same lesson (word bigrams, and the closest
single pair), so a reader can judge how far the two generators' phrasing overlaps.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_queries import advice_lessons  # noqa: E402

OUT = ROOT / "evals" / "bench" / "triggers.jsonl"
QUERIES = ROOT / "evals" / "bench" / "queries.jsonl"
KINDS = {"task": 4, "symptom": 3, "vocabulary": 3}


def bigrams(text: str) -> set[tuple[str, str]]:
    """Lower-cased adjacent word pairs, for the overlap report."""
    w = re.findall(r"[a-z0-9]+", text.lower())
    return set(zip(w, w[1:], strict=False))


def main() -> None:
    """Validate the batches, write the trigger file, and report its overlap with the queries."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batches", type=Path)
    ap.add_argument("--generator", required=True)
    args = ap.parse_args()
    lessons = advice_lessons()
    rows, problems = [], []
    for path in sorted(args.batches.glob("triggers-*.jsonl")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                t = json.loads(line)
            except ValueError:
                problems.append(f"{path.name}:{i}: not JSON")
                continue
            text = (t.get("text") or "").strip()
            if t.get("lesson") not in lessons:
                problems.append(f"{path.name}:{i}: unknown lesson {t.get('lesson')!r}")
            elif t.get("kind") not in KINDS:
                problems.append(f"{path.name}:{i}: kind {t.get('kind')!r}")
            elif not 5 <= len(text.split()) <= 25:
                problems.append(f"{path.name}:{i}: {len(text.split())} words")
            else:
                rows.append({"lesson": t["lesson"], "kind": t["kind"], "text": text})
    kinds: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        kinds[r["lesson"]][r["kind"]] += 1
    problems += [f"{lesson}: kinds {dict(kinds.get(lesson, {}))}" for lesson in lessons
                 if dict(kinds.get(lesson, {})) != KINDS]
    if problems:
        print("\n".join(problems[:40]), file=sys.stderr)
        sys.exit(f"assemble: {len(problems)} problem(s); triggers.jsonl not written")
    with OUT.open("w") as f:
        for r in sorted(rows, key=lambda r: (r["lesson"], list(KINDS).index(r["kind"]))):
            f.write(json.dumps({**r, "generator": args.generator}) + "\n")

    # Overlap with the bench's queries for the same lesson, reported for scrutiny.
    queries = [json.loads(x) for x in QUERIES.read_text().splitlines() if x.strip()]
    by_lesson: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_lesson[r["lesson"]].append(r["text"])
    shares, closest = [], 0.0
    for q in queries:
        qb = bigrams(q["text"])
        if not qb:
            continue
        tb = set().union(*(bigrams(t) for t in by_lesson[q["lesson"]]))
        shares.append(len(qb & tb) / len(qb))
        for t in by_lesson[q["lesson"]]:
            b = bigrams(t)
            if b:
                closest = max(closest, len(qb & b) / len(qb | b))
    shares.sort()
    print(f"{len(rows)} triggers for {len(by_lesson)} lessons -> {OUT}", file=sys.stderr)
    print(f"query bigrams found in the same lesson's triggers: median {shares[len(shares) // 2]:.1%}, "
          f"90th percentile {shares[int(0.9 * (len(shares) - 1))]:.1%}; closest single query-trigger pair "
          f"(bigram Jaccard) {closest:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
