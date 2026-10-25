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
from grid_setup import REPO, governing_hits, prompt_counts, store

from okl import core  # grid_setup has put src/ on the path

print(f"store {len(store.all_nodes())} records · repo={REPO} · reranker off · limit 12")
print(f"{'hybrid':7} {'fetch':>5} {'sem-words':>9} | {'authored':>8} {'ticket':>6} {'para':>4} {'bug':>3} | six prompts' counts")
for hybrid in (None, "linear"):
    for mult in (3, 6, 9):
        for sem_words in ((None,) if hybrid is None else (None, 2)):
            core.FETCH_MULTIPLIER = mult
            core.SEMANTIC_WORD_FLOOR = sem_words
            hits = governing_hits(hybrid, "window grid")
            counts = prompt_counts(hybrid)
            print(f"{hybrid or 'off':7} {mult * 12:>5} {sem_words!s:>9} | {hits['authored']:>8} {hits['ticket']:>6} "
                  f"{hits['paraphrase']:>4} {hits['bug-report']:>3} | {', '.join(str(c) for c in counts)}")
core.FETCH_MULTIPLIER = 3
core.SEMANTIC_WORD_FLOOR = None
