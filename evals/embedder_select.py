#!/usr/bin/env python3
"""Embedder selection: which local dense model ranks the governing lesson best, on the SELECTION
set (the probe's own rephrasings plus the authored tasks; the held-out set stays clean).

    PYTHONPATH=src python3 evals/embedder_select.py <fastembed-model-id> >> evals/results/embedder-select-<date>.txt

One model per process (several in one process ran out of memory). No paid call. Per model: load
time, encode time per record, how many governing lessons the semantic arm ALONE puts in its top
twelve per variant (and the paraphrase row at 36), and the highest cosine any of the six chat
prompts draws from any record (the floor question). The model okl ships is scored through
fastembed too when its id is given, so the rows compare like with like. REPORT §4t cites the
receipt for keeping the static model: no small contextual model found more on recall, and the
cheapest cost sixty times the encode time.
"""
import ast
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from okl import semantic
from okl.client import Client

name = sys.argv[1]
store = Client()._local_store()
nodes = [n for n in store.all_nodes() if n.status not in ("retracted", "obsolete", "superseded")]
texts = [semantic.record_text(n) for n in nodes]
ids = [n.id for n in nodes]
src = Path("evals/probe_rephrase.py").read_text()
variants = ast.literal_eval(re.search(r"VARIANTS = (\{.*?\n\})\n", src, re.S).group(1))
tasks = {json.loads(line)["id"]: json.loads(line)
         for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()}
queries = []   # (label, task id, text)
for tid, t in tasks.items():
    queries.append(("authored", tid, t["task"]))
    for label, text in zip(("ticket", "paraphrase", "bug-report"), variants[tid], strict=True):
        queries.append((label, tid, text))
prompts = json.loads(Path("evals/probe_prompts.json").read_text())["prompts"]
if len(sys.argv) > 2 and sys.argv[2] == "--header":
    print(f"{len(nodes)} records · {len(queries)} selection queries (8 authored + 24 probe variants) · "
          f"{len(prompts)} filler prompts")
    print(f"{'model':48} {'load s':>6} {'ms/rec':>6} {'authored@12':>11} {'ticket@12':>9} {'para@12':>7} "
          f"{'bug@12':>6} {'para@36':>7} {'filler max cos':>14}")
try:
    from fastembed import TextEmbedding
    t0 = time.perf_counter()
    m = TextEmbedding(model_name=name)
    load = time.perf_counter() - t0
    t0 = time.perf_counter()
    D = np.array(list(m.passage_embed(texts)))
    enc = (time.perf_counter() - t0) / len(texts) * 1000
    Q = np.array(list(m.query_embed([q[2] for q in queries])))
    P = np.array(list(m.query_embed(prompts)))
except Exception as e:  # noqa: BLE001 - a model that will not load is a row, not a crash
    print(f"{name:48} FAILED: {str(e)[:80]}")
    sys.exit(0)
D = D / np.linalg.norm(D, axis=1, keepdims=True)
Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
P = P / np.linalg.norm(P, axis=1, keepdims=True)
sims = Q @ D.T
at12 = dict.fromkeys(("authored", "ticket", "paraphrase", "bug-report"), 0)
para36 = 0
for (label, tid, _), row in zip(queries, sims, strict=True):
    order = [ids[i] for i in np.argsort(-row)]
    rank = order.index(tasks[tid]["defect_node"]) + 1
    at12[label] += rank <= 12
    if label == "paraphrase":
        para36 += rank <= 36
fmax = float((P @ D.T).max())
print(f"{name:48} {load:6.1f} {enc:6.1f} {at12['authored']:>8}/8 {at12['ticket']:>6}/8 {at12['paraphrase']:>4}/8 "
      f"{at12['bug-report']:>3}/8 {para36:>4}/8 {fmax:14.2f}")
