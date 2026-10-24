#!/usr/bin/env python3
"""Grid for REPORT §4v (#277): the floor's one-word rule applied only to words in at most a given
share of the store, on the SELECTION set (the probe's own rephrasings and the authored tasks; the
held-out set stays clean) and the six no-match prompts.

    PYTHONPATH=src python3 evals/common_word_grid.py > evals/results/common-word-grid-<date>.txt

Rows: hybrid off and linear, times a share of None (today's rule), 0.03, 0.05, 0.10, 0.15 and
0.25. Columns: governing lessons briefed per variant (harness config), the six prompts' counts
(hook config) and how many of them are refused at the three-lesson budget. The selection rule
is the issue's: the largest share that keeps the authored row at 8 of 8 and lowers the three
heavy prompts.
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
SHARES = (None, 0.03, 0.05, 0.10, 0.15, 0.25)


def returned(res: dict) -> set[str]:
    """Ids of every record a check result briefed."""
    return {r["id"] for b in BUCKETS for r in res.get(b, [])}


print(f"store {len(store.all_nodes())} records · repo={REPO} · reranker off · limit 12 · budget 3")
print(f"{'hybrid':7} {'share':>5} | {'authored':>8} {'ticket':>6} {'para':>4} {'bug':>3} | refused  six prompts' counts")
for hybrid in (None, "linear"):
    for share in SHARES:
        core.COMMON_WORD_SHARE = share
        hits = dict.fromkeys(LABELS, 0)
        for tid, t in tasks.items():
            for label, text in zip(LABELS, [t["task"], *variants[tid]], strict=True):
                res = core.check(store, repo=REPO, task=text, interests=None, hybrid=hybrid)
                if hybrid and res.get("hybrid_unavailable"):
                    sys.exit(f"grid: {res['hybrid_unavailable']}")
                hits[label] += t["defect_node"] in returned(res)
        counts = [len(returned(core.check(store, repo=REPO, task=p, interests=INTERESTS, hybrid=hybrid)))
                  for p in prompts]
        print(f"{hybrid or 'off':7} {share if share is not None else 'off':>5} | {hits['authored']:>8} {hits['ticket']:>6} "
              f"{hits['paraphrase']:>4} {hits['bug-report']:>3} | {sum(c <= 3 for c in counts)} of 6  "
              f"{', '.join(str(c) for c in counts)}")
core.COMMON_WORD_SHARE = None
