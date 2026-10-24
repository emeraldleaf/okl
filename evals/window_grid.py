#!/usr/bin/env python3
"""Window grid for REPORT §4u: the first stage's fetch per arm, and the floor's two-word rule
for a candidate only the semantic arm returned, on the SELECTION set (the probe's own
rephrasings and the authored tasks; the held-out set stays clean) and the six precision prompts.

    PYTHONPATH=src python3 evals/window_grid.py > evals/results/window-grid-<date>.txt

Each row is one configuration of core.check: hybrid off or linear, FETCH_MULTIPLIER 3 (today's
36 per arm), 6 or 9, and SEMANTIC_WORD_FLOOR None (today's rule: a semantic-only candidate
passes by cosine alone) or 2 (it also passes by sharing two subject words). The columns are
the probe's own measures: governing lessons briefed per variant (harness config) and the six
prompts' returned counts (hook config). The reranker is off throughout: this is the first
stage and the floor.
"""
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
from okl import core
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
BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones",
           "threat_prior_art", "vocabulary", "decisions", "context")


def returned(res: dict) -> set[str]:
    """Ids of every record a check result briefed."""
    return {r["id"] for b in BUCKETS for r in res.get(b, [])}


print(f"store {len(store.all_nodes())} records · repo={REPO} · reranker off · limit 12")
print(f"{'hybrid':7} {'fetch':>5} {'sem-words':>9} | {'authored':>8} {'ticket':>6} {'para':>4} {'bug':>3} | six prompts' counts")
for hybrid in (None, "linear"):
    for mult in (3, 6, 9):
        for sem_words in ((None,) if hybrid is None else (None, 2)):
            core.FETCH_MULTIPLIER = mult
            core.SEMANTIC_WORD_FLOOR = sem_words
            hits = dict.fromkeys(LABELS, 0)
            for tid, t in tasks.items():
                for label, text in zip(LABELS, [t["task"], *variants[tid]], strict=True):
                    res = core.check(store, repo=REPO, task=text, interests=None, hybrid=hybrid)
                    if hybrid and res.get("hybrid_unavailable"):
                        sys.exit(f"window grid: {res['hybrid_unavailable']}")
                    hits[label] += t["defect_node"] in returned(res)
            counts = [len(returned(core.check(store, repo=REPO, task=p, interests=INTERESTS, hybrid=hybrid)))
                      for p in prompts]
            print(f"{hybrid or 'off':7} {mult * 12:>5} {sem_words!s:>9} | {hits['authored']:>8} {hits['ticket']:>6} "
                  f"{hits['paraphrase']:>4} {hits['bug-report']:>3} | {', '.join(str(c) for c in counts)}")
core.FETCH_MULTIPLIER = 3
core.SEMANTIC_WORD_FLOOR = None
