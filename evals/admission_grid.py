#!/usr/bin/env python3
"""Admission grid for REPORT §4u: can the first stage's cosine and the second stage's rank,
together, admit the lessons the reranker lifts that the word floor drops, without admitting
chat filler? Selection set only (the probe's own rephrasings and the authored tasks; the
held-out set stays clean for the measurement) plus the six precision prompts.

    PYTHONPATH=src python3 evals/admission_grid.py > evals/results/admission-grid-<date>.txt

For every query the candidates are check's own window (36 per arm, linear fusion) with the
first 24 reranked. A candidate the §4n floor drops is "admitted" by the cell (c, k) when the
semantic arm scored it at cosine >= c and the reranker ranked it <= k. The table counts, per
cell, how many governing lessons the floor currently drops would be admitted, and how many
records the six chat prompts would gain. The rows above it show each dropped governing
lesson's cosine and rank, and each chat prompt's best dropped candidates, so the table can be
checked by hand.
"""
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
from okl import core, semantic
from okl.client import Client, load_config

store = Client()._local_store()
cfg = load_config()
REPO = cfg.get("repo") or "okl"
INTERESTS = cfg.get("interests")
src = Path("evals/probe_rephrase.py").read_text()
variants = ast.literal_eval(re.search(r"VARIANTS = (\{.*?\n\})\n", src, re.S).group(1))
tasks = {json.loads(line)["id"]: json.loads(line)
         for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()}
prompts = json.loads(Path("evals/probe_prompts.json").read_text())["prompts"]
LABELS = ("authored", "ticket", "paraphrase", "bug-report")
COSINES = (0.0, 0.25, 0.30, 0.35)
RANKS = (1, 2, 3, 5)


def pool_view(text: str, interests: list[str] | None) -> tuple[list[dict], set[str]]:
    """Each in-scope live candidate of check's window with its cosine, reranker rank and
    whether the floor keeps it, plus the ids the floor keeps."""
    cand = core.ranked_candidates(store, text, 36, "linear", rerank=True)
    if cand.rerank_note:
        sys.exit(f"admission grid: the reranker did not run ({cand.rerank_note})")
    scope = f"repo:{REPO}"
    live = [n for n in cand.nodes if core._in_scope(n, scope, interests) and n.status not in core.RETIRED_STATUSES]
    kept, _matched, _weak = core._apply_floor(store, live, core.briefing_terms(text), cand)
    kept_ids = {n.id for n in kept}
    rank = {n.id: i + 1 for i, n in enumerate(cand.nodes[:core.rerank_stage.RERANK_POOL])}
    rows = [{"id": n.id, "title": n.title, "cos": cand.scores.get(n.id), "rank": rank.get(n.id),
             "lexical": n.id in cand.lexical, "kept": n.id in kept_ids} for n in live]
    return rows, kept_ids


def admitted(row: dict, c: float, k: int) -> bool:
    """The cell's rule on one dropped candidate."""
    return (not row["kept"] and row["cos"] is not None and row["cos"] >= c
            and row["rank"] is not None and row["rank"] <= k)


print(f"store {len(store.all_nodes())} records · repo={REPO} · window 36 per arm, linear, reranked pool "
      f"{core.rerank_stage.RERANK_POOL} · floor {semantic.SUBJECT_SIMILARITY} cosine for a semantic-only candidate")
print("\nA. Governing lessons the floor DROPS on the selection set (harness config), with what the rule would see:")
print(f"{'task':16} {'variant':11} {'in pool':7} {'lexical':7} {'cosine':>6} {'rank':>4}")
dropped: list[dict] = []
for tid, t in tasks.items():
    for label, text in zip(LABELS, [t["task"], *variants[tid]], strict=True):
        rows, kept_ids = pool_view(text, None)
        g = next((r for r in rows if r["id"] == t["defect_node"]), None)
        if g is None or g["kept"]:
            continue
        dropped.append({**g, "task": tid, "variant": label})
        print(f"{tid:16} {label:11} {'yes' if g['rank'] else 'no':7} {'yes' if g['lexical'] else 'no':7} "
              f"{g['cos'] if g['cos'] is None else round(g['cos'], 2)!s:>6} {g['rank']!s:>4}")
print(f"{len(dropped)} governing lessons dropped of {len(tasks) * len(LABELS)} queries")

print("\nB. The six chat prompts (hook config): records the floor drops, best three by reranker rank, with cosine:")
chat: list[list[dict]] = []
for p in prompts:
    rows, kept_ids = pool_view(p, INTERESTS)
    drop = sorted((r for r in rows if not r["kept"] and r["rank"] is not None), key=lambda r: r["rank"])
    chat.append(drop)
    best = [(r["rank"], None if r["cos"] is None else round(r["cos"], 2), r["title"][:40]) for r in drop[:3]]
    print(f"  kept {len(kept_ids):2} · dropped {len(drop):2} · {best}  <- {p[:44]!r}")

print("\nC. GRID: governing lessons admitted (of the dropped ones above) / records the six prompts would gain in total")
print(f"{'cosine >=':>10} " + " ".join(f"{'rank <= ' + str(k):>14}" for k in RANKS))
for c in COSINES:
    cells = []
    for k in RANKS:
        gain = sum(admitted(r, c, k) for r in dropped)
        filler = sum(admitted(r, c, k) for drop in chat for r in drop)
        per_prompt = [sum(admitted(r, c, k) for r in drop) for drop in chat]
        cells.append(f"{gain:>2} / {filler:>2} {''.join(str(x) for x in per_prompt):>7}")
    print(f"{c:>10} " + " ".join(f"{cell:>14}" for cell in cells))
print("(each cell: lessons admitted / filler records admitted, then the six prompts' gains as digits)")
