#!/usr/bin/env python3
"""How well a model ORDERS lessons, and how well its score SEPARATES them from null prompts (#291).

    PYTHONPATH=src python3 evals/bench/rank_quality.py --model lightonai/LateOn \\
        --triggers evals/bench/triggers.jsonl > evals/results/bench-<date>-sel-rank-<name>.txt

The decision runners measure a model inside a briefing decision. This one separates the two
jobs a model could do. Ordering: for each query, the governing lesson's position when every
in-scope live lesson is ranked by the model's score, as hit@1, hit@3, hit@12 and MRR, beside
the same figures for the full-text search with triggers on the same queries. Deciding: the
AUC of the governing lesson's score against the best score of each calibration-half null
prompt, the separation a line on that score could use. A model can order well and decide
badly; then it belongs after the decision, ordering what the decision lets through.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as bench
import run_dense
import v2


def about_parts(n: v2.Node) -> list[str]:
    """A lesson's about-text in parts: title with symptom, each alias, each trigger."""
    parts = [". ".join(x for x in (n.title, n.symptom) if x)]
    parts += [a.strip() for a in (n.aliases or "").split(";") if a.strip()]
    return parts + [t.strip() for t in (n.triggers or "").splitlines() if t.strip()]


def summary(ranks: list[int]) -> str:
    """hit@1, hit@3, hit@12 and MRR over a list of 1-based ranks."""
    n = len(ranks)
    return (f"hit@1 {sum(r == 1 for r in ranks) / n:.1%} · hit@3 {sum(r <= 3 for r in ranks) / n:.1%} · "
            f"hit@12 {sum(r <= 12 for r in ranks) / n:.1%} · MRR {sum(1 / r for r in ranks) / n:.3f}")


def main() -> None:
    """Rank the in-scope corpus by the model for every selection query, and score the nulls."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--triggers", type=Path)
    ap.add_argument("--split", choices=["selection", "heldout", "all"], default="selection")
    ap.add_argument("--no-prompts", action="store_true", help="skip the model card's retrieval prompts")
    args = ap.parse_args()
    queries = [json.loads(x) for x in bench.QUERIES.read_text().splitlines() if x.strip()]
    if args.split != "all":
        queries = [q for q in queries if q["split"] == args.split]
    nulls = [json.loads(x) for x in bench.NULLS.read_text().splitlines() if x.strip()]
    calib = [p for p in nulls if int(hashlib.sha256(p["id"].encode()).hexdigest(), 16) % 2 == 0]
    enc = run_dense.Encoder(args.model, prompts=not args.no_prompts)
    with tempfile.TemporaryDirectory() as tmp:
        store = bench.build_corpus(Path(tmp))
        n_trig = bench.load_triggers(store, args.triggers) if args.triggers else 0
        nodes = [n for n in store.all_nodes() if n.status not in v2.core.RETIRED_STATUSES]
        if enc.late:
            docs = enc.encode([". ".join(about_parts(n)) for n in nodes])
        else:
            owners, texts = [], []
            for i, n in enumerate(nodes):
                for p in about_parts(n):
                    owners.append(i)
                    texts.append(p)
            matrix = np.stack(enc.encode(texts))
            owner = np.array(owners)

        def scores(text: str, repo: str) -> dict[str, float]:
            q = enc.encode([text], query=True)[0]
            visible = [i for i, n in enumerate(nodes) if v2.core._in_scope(n, f"repo:{repo}", None)]
            if enc.late:
                return {nodes[i].id: run_dense.maxsim(q, docs[i]) for i in visible}
            sims = matrix @ q
            best = np.full(len(nodes), -1.0)
            np.maximum.at(best, owner, sims)
            return {nodes[i].id: float(best[i]) for i in visible}

        model_ranks, fts_ranks, gov = [], [], []
        for q in queries:
            repo = bench.repo_for(store, q["lesson"])
            sc = scores(q["text"], repo)
            order = sorted(sc, key=lambda k: -sc[k])
            model_ranks.append(order.index(q["lesson"]) + 1)
            gov.append(sc[q["lesson"]])
            fts = bench.rank_of(store, q["text"], q["lesson"], repo=repo, hybrid=None, rerank=False,
                                n_all=len(nodes))
            fts_ranks.append(fts or len(nodes))
        null_best = [max(scores(p["text"], bench.REPO).values()) for p in calib]
    auc = sum((g > n) + 0.5 * (g == n) for g in gov for n in null_best) / (len(gov) * len(null_best))
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=bench.ROOT, check=False).stdout.strip()
    print(f"bench rank quality · model {args.model} ({'late interaction' if enc.late else 'dense, best of the about-text parts'}) · "
          f"split {args.split} · code {commit}"
          + (f" · prompts {enc.prompts[0]!r} / {enc.prompts[1]!r}" if enc.prompts else ""))
    print(f"{len(queries)} queries · {len(nodes)} live records · triggers on {n_trig} lessons · "
          f"{len(calib)} calibration-half null prompts")
    print(f"ordering, the model:                          {summary(model_ranks)}")
    print(f"ordering, full-text with triggers (no model): {summary(fts_ranks)}  (a lesson the search never returns counts as last)")
    print(f"deciding: governing-lesson score median {statistics.median(gov):.3f} · null prompts' best median "
          f"{statistics.median(null_best):.3f} · AUC {auc:.3f}")


if __name__ == "__main__":
    main()
