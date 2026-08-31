# Evals — the measurement tier (surface 5, for behavior)

The gates in `gates/` catch drift in *artifacts* (docs, identifiers, canon size). This tier catches
drift in *behavior* — did the change make the system measurably worse? It is here because the RAG service's
single most dangerous defect was a metric that could not report its own unreliability
("LLM Judge 5.0/5.0 while 19 of 20 cases crashed").

## The three rules this harness enforces (earned, not invented)

1. **A metric that cannot report its own failure rate is not a metric.** `run_evals.py` leads with
   its failure count and prints `❌ RESULTS NOT USABLE` above a configurable failure-rate threshold —
   *before* any score. A green average over a crashed suite is the failure mode to prevent.
2. **The judge must not grade its own homework.** If you use an LLM judge, it must be a different
   model from the generator. The harness refuses to run if `JUDGE_MODEL == GENERATOR_MODEL`.
3. **Bake in the error-analysis cross-tab.** Every eval run emits the `retrieval_hit × judge_score`
   (or your task's equivalent `precondition × outcome`) cross-tab, because that 2×2 is the only thing
   that told the RAG service which component was actually failing. It runs on every eval, not as a one-off.

## Golden set from real failures — not invented fixtures

Rule 4 of the method: *fixtures you invented cannot falsify assumptions you hold.* Seed `cases.jsonl`
from real inputs that actually broke (the RAG service used its 25 real EDGAR filenames verbatim), not from
hand-written happy-path examples.

## Files
- `run_evals.py` — the harness (framework-agnostic; adapt `evaluate_one()` to your system)
- `cases.jsonl` — the golden set (`<<FILL>>` with real cases)
- results write to `results/` with the failure count and cross-tab at the top

## Wire into CI
Add to `ci/` after the gates: a regression fails the build if the usable pass-rate drops below the
committed baseline. Never quote a number from a run whose failure rate tripped `RESULTS NOT USABLE`.
