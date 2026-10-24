#!/usr/bin/env python3
"""Reranker selection: which local cross-encoder, over which fused window, on the SELECTION set.

    PYTHONPATH=src python3 evals/rerank_select.py <model-id> >> evals/results/rerank-select-<date>.txt

One model per process (several ONNX sessions in one process ran out of memory). No paid call.
The selection set is the probe's own rephrasings (`VARIANTS` in evals/probe_rephrase.py) plus
the authored tasks, so the held-out set stays clean for the measurement (REPORT §4t). For
each fused window (18 and 36 per arm, linear fusion), every fused candidate is scored by the
cross-encoder against the task on the record's short text (title, symptom, aliases). The row
prints the load time, the median time per task, how many governing lessons sit in the top
twelve per variant, the authored lessons' ranks, and the best score each of the six chat
prompts drew (the floor question: is there an absolute line?).
"""
import ast
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from okl import core, rerank
from okl.client import Client

model = sys.argv[1] if len(sys.argv) > 1 else rerank.MODEL_ID
store = Client()._local_store()
src = Path("evals/probe_rephrase.py").read_text()
variants = ast.literal_eval(re.search(r"VARIANTS = (\{.*?\n\})\n", src, re.S).group(1))
tasks = {json.loads(line)["id"]: json.loads(line)
         for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()}
prompts = json.loads(Path("evals/probe_prompts.json").read_text())["prompts"]
LABELS = ("authored", "ticket", "paraphrase", "bug-report")

t0 = time.perf_counter()
encoder = rerank.load_model(model, offline=False)
load = time.perf_counter() - t0
for window in (18, 36):
    hits = dict.fromkeys(LABELS, 0)
    lat: list[float] = []
    ranks: list[int | None] = []
    for tid, t in tasks.items():
        for label, text in zip(LABELS, [t["task"], *variants[tid]], strict=True):
            nodes = core.ranked_candidates(store, text, window, "linear").nodes
            s = time.perf_counter()
            scores = [float(x) for x in encoder.rerank(text, [rerank.pair_text(n) for n in nodes])]
            lat.append(time.perf_counter() - s)
            order = [n.id for n, _ in sorted(zip(nodes, scores, strict=True), key=lambda p: -p[1])]
            rank = order.index(t["defect_node"]) + 1 if t["defect_node"] in order else None
            hits[label] += bool(rank and rank <= 12)
            if label == "authored":
                ranks.append(rank)
    fill = []
    for p in prompts:
        nodes = core.ranked_candidates(store, p, window, "linear").nodes
        fill.append(max(float(x) for x in encoder.rerank(p, [rerank.pair_text(n) for n in nodes])))
    print(f"{model:36} w{window:<3} load {load:4.1f}s  {statistics.median(lat)*1000:5.0f} ms/task  "
          f"authored {hits['authored']}/8 (ranks {ranks})  ticket {hits['ticket']}/8  "
          f"paraphrase {hits['paraphrase']}/8  bug {hits['bug-report']}/8  "
          f"filler top scores {[round(x, 1) for x in fill]}")
