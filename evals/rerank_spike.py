#!/usr/bin/env python3
"""The first reranker spike (REPORT §4t's pre-flight): a cross-encoder over the fused window, on
the held-out tasks, with the record's full text.

    PYTHONPATH=src python3 evals/rerank_spike.py [--model <id>] [--window 36] [--text full|short] \
        > evals/results/rerank-spike-<date>-<model>.txt

No paid call. For each held-out task (evals/heldout_tasks.jsonl) and each authored task, the
candidates are the fused window `core.ranked_candidates(..., window, "linear")` gives (up to
twice the window), scored by the cross-encoder against the task text; the receipt prints the
governing lesson's rank before and after, its score beside the best other score, and the time
per task. The six precision prompts print their score distribution. This spike read the
held-out set before the selection set existed, which §4t states; `rerank_select.py` is the
script the model was then chosen with.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from okl import core, rerank, semantic
from okl.client import Client

ap = argparse.ArgumentParser()
ap.add_argument("--model", default=rerank.MODEL_ID)
ap.add_argument("--window", type=int, default=36)
ap.add_argument("--text", choices=["full", "short"], default="full",
                help="what the cross-encoder reads per record: the full record text, or title+symptom+aliases")
args = ap.parse_args()

t0 = time.perf_counter()
encoder = rerank.load_model(args.model, offline=False)
load_s = time.perf_counter() - t0
store = Client()._local_store()
held = [json.loads(line) for line in Path("evals/heldout_tasks.jsonl").read_text().splitlines() if line.strip()]
authored = [json.loads(line) for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()]
prompts = json.loads(Path("evals/probe_prompts.json").read_text())["prompts"]
record_text = semantic.record_text if args.text == "full" else rerank.pair_text
print(f"model {args.model} · load {load_s:.1f} s · store {len(store.all_nodes())} records, "
      f"{len(store.embeddings(semantic.MODEL_ID))} with a vector · window {args.window} per arm · text {args.text}")


def scored(task: str) -> tuple[list, list, float]:
    """The fused candidates, the same candidates in the cross-encoder's order with scores, and the time."""
    nodes = core.ranked_candidates(store, task, args.window, "linear").nodes
    t = time.perf_counter()
    scores = [float(x) for x in encoder.rerank(task, [record_text(n) for n in nodes])]
    dt = time.perf_counter() - t
    order = sorted(zip(nodes, scores, strict=True), key=lambda p: -p[1])
    return nodes, order, dt


print(f"\n{'task':28} {'before':>6} {'after':>5}  {'gov score':>9} {'best other':>10}  {'pairs':>5} {'ms':>6}")
rows = {"ticket": [0, 0], "paraphrase": [0, 0], "bug-report": [0, 0]}
lat = []
for t in held:
    nodes, order, dt = scored(t["task"])
    ids_before = [n.id for n in nodes]
    ids_after = [n.id for n, _ in order]
    g = t["defect_node"]
    before = ids_before.index(g) + 1 if g in ids_before else None
    after = ids_after.index(g) + 1 if g in ids_after else None
    gov = next((s for n, s in order if n.id == g), None)
    other = max((s for n, s in order if n.id != g), default=None)
    label = t["variant"]
    rows[label][1] += 1
    rows[label][0] += bool(after and after <= 12)
    lat.append(dt)
    print(f"{t['id']:28} {before!s:>6} {after!s:>5}  {gov if gov is None else round(gov, 2)!s:>9} "
          f"{round(other, 2) if other is not None else None!s:>10}  {len(nodes):>5} {dt*1000:6.0f}")
print("\nheld-out: governing lesson in the top 12 after reranking:",
      {k: f"{v[0]}/{v[1]}" for k, v in rows.items()},
      f"· median {statistics.median(lat)*1000:.0f} ms per task, max {max(lat)*1000:.0f} ms")

print("\nauthored tasks: governing rank after reranking (must stay in the top 12):")
for t in authored:
    nodes, order, dt = scored(t["task"])
    ids_after = [n.id for n, _ in order]
    after = ids_after.index(t["defect_node"]) + 1 if t["defect_node"] in ids_after else None
    gov = next((s for n, s in order if n.id == t["defect_node"]), None)
    print(f"  {t['id']:16} rank {after}  score {gov if gov is None else round(gov, 2)}")

print("\nprecision prompts: reranker scores of the fused window (top 5, and how many at or above -2 / 0 / 2):")
for p in prompts:
    nodes, order, dt = scored(p)
    scores = [s for _, s in order]
    print(f"  top={[round(s, 1) for s in scores[:5]]}  n>=-2:{sum(s >= -2 for s in scores)} "
          f"n>=0:{sum(s >= 0 for s in scores)} n>=2:{sum(s >= 2 for s in scores)}  {p[:48]!r}")
