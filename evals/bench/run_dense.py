#!/usr/bin/env python3
"""A dense arm beside the v2 evidence score: multi-vector, best match per lesson (#291).

    PYTHONPATH=src python3 evals/bench/run_dense.py --model BAAI/bge-small-en-v1.5 \\
        --triggers evals/bench/triggers.jsonl > evals/results/bench-<date>-dense-<name>.txt

Each lesson is embedded as several texts: its title with its symptom, each alias, and each
trigger. A prompt's score for a lesson is its best cosine over those vectors (max-sim, the
multi-vector form Doc2Query++ and HyPE found to beat appending generated text to one
document). Candidates are the union of the full-text window and the dense window (36 each).
The decision score is evidence + W * maxsim, with W from a grid on this split; the line is
set by split conformal on half the null prompts and tested on the other half, as in
run_v2.py. Also recorded: the model's load time in a fresh process (what a prompt hook pays
on every prompt) and the per-prompt encode time.
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

from okl import hub

WEIGHTS = (0.0, 5.0, 10.0, 20.0, 40.0)
CAPS = (3, 5)
ALPHA = 0.05


class Encoder:
    """One model behind one call: fastembed's TextEmbedding, or model2vec for potion models."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        t0 = time.perf_counter()
        if model_id.startswith("minishlab/"):
            from model2vec import StaticModel
            self._m = StaticModel.from_pretrained(model_id)
            self._kind = "m2v"
        else:
            from fastembed import TextEmbedding
            self._m = TextEmbedding(model_name=model_id, cache_dir=str(hub.model_cache_dir()))
            self._kind = "fe"
        self.load_s = time.perf_counter() - t0

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Unit-length vectors, so a dot product is a cosine."""
        if self._kind == "m2v":
            raw = [list(map(float, v)) for v in self._m.encode(texts)]
        else:
            raw = [list(map(float, v)) for v in self._m.embed(texts)]
        out = []
        for v in raw:
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / n for x in v])
        return out


def cold_load_seconds(model_id: str) -> float:
    """The model's load time in a fresh interpreter, as a hook process pays it."""
    code = ("import sys,time;sys.path.insert(0,'evals/bench');sys.path.insert(0,'src');t=time.perf_counter();"
            f"import run_dense;run_dense.Encoder({model_id!r});print(time.perf_counter()-t)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=bench.ROOT, check=False)
    try:
        return float(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return float("nan")


def main() -> None:
    """Embed the corpus as multi-vectors, score prompts, and print the weight-by-cap grid."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--triggers", type=Path)
    ap.add_argument("--split", choices=["selection", "heldout", "all"], default="selection")
    args = ap.parse_args()
    queries = [json.loads(x) for x in bench.QUERIES.read_text().splitlines() if x.strip()]
    if args.split != "all":
        queries = [q for q in queries if q["split"] == args.split]
    nulls = [json.loads(x) for x in bench.NULLS.read_text().splitlines() if x.strip()]
    calib = [p for p in nulls if int(hashlib.sha256(p["id"].encode()).hexdigest(), 16) % 2 == 0]
    test = [p for p in nulls if p not in calib]
    enc = Encoder(args.model)

    with tempfile.TemporaryDirectory() as tmp:
        store = bench.build_corpus(Path(tmp))
        n_trig = bench.load_triggers(store, args.triggers) if args.triggers else 0
        index = v2.build_index(store)
        nodes = [n for n in store.all_nodes() if n.status not in v2.core.RETIRED_STATUSES]
        owner, texts = [], []
        for n in nodes:
            parts = [". ".join(x for x in (n.title, n.symptom) if x)]
            parts += [a.strip() for a in (n.aliases or "").split(";") if a.strip()]
            parts += [t.strip() for t in (n.triggers or "").splitlines() if t.strip()]
            for p in parts:
                owner.append(n.id)
                texts.append(p)
        t0 = time.perf_counter()
        vecs = enc.encode(texts)
        index_s = time.perf_counter() - t0

        encode_ms: list[float] = []

        def score_all(task: str) -> list[tuple[str, float, float]]:
            """(lesson, evidence, maxsim) for the union of both windows; [] when gated."""
            terms = v2.subject(task)
            if v2.from_harness(task) or not terms:
                return []
            t1 = time.perf_counter()
            q = enc.encode([task])[0]
            encode_ms.append((time.perf_counter() - t1) * 1000)
            best: dict[str, float] = {}
            for nid, v in zip(owner, vecs, strict=True):
                c = sum(a * b for a, b in zip(q, v, strict=True))
                if c > best.get(nid, -1.0):
                    best[nid] = c
            dense = sorted(best, key=lambda k: -best[k])[:36]
            lex = [n.id for n in store.search(" ".join(terms), limit=36)]
            ids = list(dict.fromkeys(lex + dense))
            return [(nid, v2.evidence(index, terms, nid), best.get(nid, 0.0)) for nid in ids]

        q_sc = [(q, score_all(q["text"])) for q in queries]
        c_sc = [score_all(p["text"]) for p in calib]
        t_sc = [score_all(p["text"]) for p in test]

    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=bench.ROOT, check=False).stdout.strip()
    print(f"bench dense arm · model {args.model} · split {args.split} · code {commit}")
    print(f"corpus: {index.n} live records, {len(texts)} vectors (title+symptom, aliases, triggers on {n_trig} lessons) · "
          f"queries sha {bench.digest([bench.QUERIES])} · nulls {len(nulls)}: {len(calib)} calibrate, {len(test)} test")
    print(f"cost: cold load in a fresh process {cold_load_seconds(args.model):.2f} s · load here {enc.load_s:.2f} s · "
          f"index {index_s:.1f} s · encode per prompt median {statistics.median(encode_ms):.1f} ms")
    print(f"decision score = evidence + W * maxsim; line at alpha {ALPHA} by split conformal\n")
    print(f"{'W':>5} {'line':>7} {'cap':>3} | {'recall [95%]':>22} {'briefed/q':>9} | null test briefed anything [95%] | paraphrase")
    for w in WEIGHTS:
        def top(sc: list[tuple[str, float, float]], w: float = w) -> list[tuple[str, float]]:
            return sorted(((nid, e + w * m) for nid, e, m in sc), key=lambda t: -t[1])
        line = v2.conformal_line([max((s for _n, s in top(sc)), default=0.0) for sc in c_sc], ALPHA)
        for cap in CAPS:
            by_lesson: dict[str, list[float]] = defaultdict(list)
            counts, para = [], [0, 0]
            for q, sc in q_sc:
                ids = [nid for nid, s in top(sc) if s >= line][:cap]
                hit = q["lesson"] in ids
                by_lesson[q["lesson"]].append(1.0 if hit else 0.0)
                counts.append(len(ids))
                if q["register"] == "paraphrase":
                    para[0] += hit
                    para[1] += 1
            m, lo, hi = bench.boot_ci(by_lesson)
            briefed = sum(1 for sc in t_sc if any(s >= line for _n, s in top(sc)))
            wlo, whi = bench.wilson(briefed, len(t_sc))
            print(f"{w:>5} {line:>7.3f} {cap:>3} | {m:>7.1%} [{lo:5.1%}, {hi:5.1%}] {statistics.mean(counts):>9.2f} | "
                  f"{briefed} of {len(t_sc)} ({briefed / len(t_sc):.1%}, [{wlo:.1%}, {whi:.1%}]) | {para[0]}/{para[1]}")


if __name__ == "__main__":
    main()
