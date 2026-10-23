#!/usr/bin/env python3
"""The semantic subject line, chosen by a grid (REPORT §4q): for each line and fusion mode,
the probe's recall rows and the six precision prompts, on the live store.

    PYTHONPATH=src python3 evals/hybrid_grid.py > evals/results/hybrid-grid-<date>.txt

The selection rule is written in REPORT §4q before this runs; this script only prints the cells.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from okl import core, semantic
from okl.client import Client

store = Client()._local_store()
REPO = "okl"
tasks = [json.loads(line) for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()]
heldout = json.loads(Path("evals/heldout_variants.json").read_text())
prompts = json.loads(Path("evals/probe_prompts.json").read_text())["prompts"]
INTERESTS = Client().interests or None
BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones", "threat_prior_art", "vocabulary", "decisions", "context")
PROBE_VARIANTS = {t["id"]: t for t in tasks}


def ids(task: str, hybrid: str | None, interests: list[str] | None) -> list[str]:
    """The briefed ids for `task` under one setting."""
    res = core.check(store, repo=REPO, task=task, interests=interests, hybrid=hybrid)
    return [r["id"] for b in BUCKETS for r in res.get(b, [])]


def recall(hybrid: str | None, variants: dict[str, dict[str, str]], label: str) -> int:
    """How many of the eight tasks' governing records are briefed for the `label` variant."""
    return sum(t["defect_node"] in ids(variants[t["id"]][label], hybrid, None) for t in tasks)


print(f"store: {len(store.all_nodes())} records · {len(store.embeddings(semantic.MODEL_ID))} with a vector · hook interests={INTERESTS}")
print("line   mode    authored  held-out ticket/paraphrase/bug  precision prompts (hook config)")
base = {p: len(ids(p, None, INTERESTS)) for p in prompts}
print(f"  -    off     {sum(t['defect_node'] in ids(t['task'], None, None) for t in tasks)}/8       "
      f"{recall(None, heldout, 'ticket')}/{recall(None, heldout, 'paraphrase')}/{recall(None, heldout, 'bug-report')}            "
      + " ".join(f"{base[p]:2}" for p in prompts))
for line in (0.25, 0.30, 0.35, 0.40):
    semantic.SUBJECT_SIMILARITY = line
    for mode in ("rrf", "linear"):
        authored = sum(t["defect_node"] in ids(t["task"], mode, None) for t in tasks)
        rows = [recall(mode, heldout, lab) for lab in ("ticket", "paraphrase", "bug-report")]
        prec = [len(ids(p, mode, INTERESTS)) for p in prompts]
        print(f"{line:.2f}   {mode:6}  {authored}/8       {rows[0]}/{rows[1]}/{rows[2]}            "
              + " ".join(f"{c:2}" for c in prec))
