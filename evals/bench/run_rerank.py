#!/usr/bin/env python3
"""Recent cross-encoder rerankers as the briefing decision, on the bench (#291).

    PYTHONPATH=src python3 evals/bench/run_rerank.py --model gte-modernbert \\
        --triggers evals/bench/triggers.jsonl > evals/results/bench-<date>-sel-rerank-<name>.txt

The candidates are the first of the in-scope full-text window (triggers indexed) that the
calibrated decision reads: --pool of them, 24 by default. A reranker scores each (prompt, lesson) pair, the lesson as its title, symptom
and fix (the unexpanded text: expansion helps weak first stages and can hurt strong scorers,
Weller et al., EACL 2024). The decision is the same procedure as everywhere else on the bench:
brief the candidates at or above a line set by split conformal at alpha 0.05 over the
calibration half of the null prompts, best first, at most five; the unseen half tests it.

Models, run through onnxruntime directly because fastembed does not carry them:
- gte-modernbert: Alibaba-NLP/gte-reranker-modernbert-base, onnx/model_int8.onnx; the score is
  its relevance logit.
- qwen3: onnx-community/Qwen3-Reranker-0.6B-ONNX, onnx/model_quantized.onnx; a generative judge
  asked whether the lesson applies, scored as P("yes") against P("no") at the last position,
  with the template from the model card.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
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

POOL = 24
ALPHA = 0.05
CAPS = (3, 5)
INSTRUCTION = "Given a developer's task, question or bug report, judge whether this engineering lesson applies to it"
MODELS = {"gte-modernbert": ("Alibaba-NLP/gte-reranker-modernbert-base", "onnx/model_int8.onnx"),
          "qwen3": ("onnx-community/Qwen3-Reranker-0.6B-ONNX", "onnx/model_quantized.onnx")}


class Reranker:
    """One ONNX cross-encoder: score(query, passages) -> one float per passage, higher = applies."""

    def __init__(self, name: str) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        repo, onnx_file = MODELS[name]
        t0 = time.perf_counter()
        path = hf_hub_download(repo, onnx_file)
        # Some exports keep their weights in a sidecar file beside the graph; most do not.
        with contextlib.suppress(Exception):
            hf_hub_download(repo, f"{onnx_file}_data")
        self.tok = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
        self.sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self.inputs = {i.name: i for i in self.sess.get_inputs()}
        self.name = name
        if name == "qwen3":
            self.yes = self.tok.token_to_id("yes")
            self.no = self.tok.token_to_id("no")
        self.load_s = time.perf_counter() - t0

    def score(self, query: str, passages: list[str]) -> list[float]:
        """A relevance score per passage."""
        import numpy as np
        if self.name == "gte-modernbert":
            self.tok.enable_truncation(512)
            self.tok.enable_padding()
            enc = self.tok.encode_batch([(query, p) for p in passages])
            feeds = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                     "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
            out = self.sess.run(None, {k: v for k, v in feeds.items() if k in self.inputs})[0]
            return [float(x) for x in np.asarray(out).reshape(len(passages), -1)[:, 0]]
        prefix = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and "
                  "the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n"
                  "<|im_start|>user\n")
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        scores = []
        for p in passages:
            text = f"{prefix}<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {p}{suffix}"
            ids = self.tok.encode(text, add_special_tokens=False).ids[-1024:]
            n = len(ids)
            feeds: dict = {"input_ids": np.array([ids], dtype=np.int64),
                           "attention_mask": np.ones((1, n), dtype=np.int64),
                           "position_ids": np.arange(n, dtype=np.int64)[None, :]}
            for name, meta in self.inputs.items():
                if name.startswith("past_key_values"):
                    shape = [1 if d in ("batch_size",) or (isinstance(d, str) and "batch" in d) else
                             0 if isinstance(d, str) else d for d in meta.shape]
                    feeds[name] = np.zeros(shape, dtype=np.float32)
            logits = self.sess.run(["logits"], {k: v for k, v in feeds.items() if k in self.inputs})[0][0, -1]
            y, no = float(logits[self.yes]), float(logits[self.no])
            m = max(y, no)
            scores.append(math.exp(y - m) / (math.exp(y - m) + math.exp(no - m)))
        return scores


def passage(n) -> str:  # noqa: ANN001 - a store Node
    """The lesson as the reranker reads it: title, symptom, fix."""
    return ". ".join(x for x in (n.title, n.symptom, n.fix) if x)


def main() -> None:
    """Rerank each prompt's window, calibrate the line on half the nulls, report the grid."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", choices=sorted(MODELS), required=True)
    ap.add_argument("--triggers", type=Path)
    ap.add_argument("--split", choices=["selection", "heldout", "all"], default="selection")
    ap.add_argument("--pool", type=int, default=POOL, help="candidates scored per prompt (default 24)")
    args = ap.parse_args()
    queries = [json.loads(x) for x in bench.QUERIES.read_text().splitlines() if x.strip()]
    if args.split != "all":
        queries = [q for q in queries if q["split"] == args.split]
    nulls = [json.loads(x) for x in bench.NULLS.read_text().splitlines() if x.strip()]
    calib = [p for p in nulls if int(hashlib.sha256(p["id"].encode()).hexdigest(), 16) % 2 == 0]
    test = [p for p in nulls if p not in calib]
    rr = Reranker(args.model)
    lat: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        store = bench.build_corpus(Path(tmp))
        n_trig = bench.load_triggers(store, args.triggers) if args.triggers else 0

        def scored(task: str, repo: str = bench.REPO) -> list[tuple[str, float]]:
            _terms, found = v2.candidates(store, task, repo, fetch=args.pool)
            if not found:
                return []
            t0 = time.perf_counter()
            s = rr.score(task, [passage(n) for n in found])
            lat.append((time.perf_counter() - t0) * 1000)
            return sorted(zip([n.id for n in found], s, strict=True), key=lambda t: -t[1])

        q_sc = [(q, scored(q["text"], bench.repo_for(store, q["lesson"]))) for q in queries]
        c_best = [max((s for _n, s in sc), default=-1e9) for sc in (scored(p["text"]) for p in calib)]
        t_sc = [scored(p["text"]) for p in test]
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=bench.ROOT, check=False).stdout.strip()
    print(f"bench reranker decision · model {MODELS[args.model][0]} ({MODELS[args.model][1]}) · split {args.split} · "
          f"code {commit}")
    print(f"pool {args.pool} in-scope full-text candidates · triggers on {n_trig} lessons · nulls {len(nulls)}: "
          f"{len(calib)} calibrate, {len(test)} test")
    print(f"cost: load {rr.load_s:.2f} s (includes download on a first run) · scoring a pool, median "
          f"{statistics.median(lat):.0f} ms, p95 {sorted(lat)[int(0.95 * (len(lat) - 1))]:.0f} ms "
          "(measured while other bench runs shared the machine)")
    line = v2.conformal_line(c_best, ALPHA)
    print(f"line at alpha {ALPHA}: {line:.4f}\n")
    for cap in CAPS:
        by_lesson: dict[str, list[float]] = defaultdict(list)
        counts, by_reg = [], defaultdict(lambda: [0, 0])
        for q, sc in q_sc:
            ids = [nid for nid, s in sc if s >= line][:cap]
            hit = q["lesson"] in ids
            by_lesson[q["lesson"]].append(1.0 if hit else 0.0)
            counts.append(len(ids))
            by_reg[q["register"]][0] += hit
            by_reg[q["register"]][1] += 1
        m, lo, hi = bench.boot_ci(by_lesson)
        b = sum(1 for sc in t_sc if any(s >= line for _n, s in sc))
        wlo, whi = bench.wilson(b, len(t_sc))
        print(f"cap {cap}: recall {m:.1%} [{lo:.1%}, {hi:.1%}] · {statistics.mean(counts):.2f} lessons a query · "
              f"unseen nulls briefed {b} of {len(t_sc)} ({b / len(t_sc):.1%}, [{wlo:.1%}, {whi:.1%}]) · "
              + " · ".join(f"{r} {h}/{n}" for r, (h, n) in sorted(by_reg.items())))


if __name__ == "__main__":
    main()
