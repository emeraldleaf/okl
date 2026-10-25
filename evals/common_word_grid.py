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
from grid_setup import REPO, governing_hits, prompt_counts, store

from okl import core  # grid_setup has put src/ on the path

SHARES = (None, 0.03, 0.05, 0.10, 0.15, 0.25)
shipped = core.COMMON_WORD_SHARE

print(f"store {len(store.all_nodes())} records · repo={REPO} · reranker off · limit 12 · budget 3")
print(f"{'hybrid':7} {'share':>5} | {'authored':>8} {'ticket':>6} {'para':>4} {'bug':>3} | refused  six prompts' counts")
for hybrid in (None, "linear"):
    for share in SHARES:
        core.COMMON_WORD_SHARE = share
        hits = governing_hits(hybrid, "common-word grid")
        counts = prompt_counts(hybrid)
        print(f"{hybrid or 'off':7} {share if share is not None else 'off':>5} | {hits['authored']:>8} {hits['ticket']:>6} "
              f"{hits['paraphrase']:>4} {hits['bug-report']:>3} | {sum(c <= 3 for c in counts)} of 6  "
              f"{', '.join(str(c) for c in counts)}")
core.COMMON_WORD_SHARE = shipped
