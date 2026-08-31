#!/usr/bin/env python3
"""Eval harness — measures behavior and, crucially, reports its own unreliability first.

Framework-agnostic: plug your system into `evaluate_one()`. The invariants it enforces are the
earned lessons, not any particular eval library (works alongside deepeval/ragas/promptfoo or none).

Usage:  python run_evals.py [--cases cases.jsonl] [--fail-rate 0.20]
Env:    GENERATOR_MODEL, JUDGE_MODEL  (must differ — rule: no grading your own homework)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def evaluate_one(case: dict) -> dict:
    """<<FILL>>: run YOUR system on `case` and return a result dict.

    Required keys in the returned dict:
      - "ok": bool            — did the case COMPLETE without crashing (not "did it pass")
      - "score": float|None   — the judge/quality score, or None if it didn't complete
      - "precondition": bool  — the x-axis of the cross-tab (e.g. retrieval_hit); task-specific
      - "outcome_bad": bool   — the y-axis (e.g. answer judged bad)
      - "error": str|None
    Replace the stub below with a real call into your app.
    """
    # STUB — deterministic placeholder so the harness runs before you wire your system.
    q = case.get("input", "")
    return {"ok": True, "score": 5.0 if q else 0.0,
            "precondition": bool(q), "outcome_bad": not bool(q), "error": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(Path(__file__).parent / "cases.jsonl"))
    ap.add_argument("--fail-rate", type=float, default=0.20,
                    help="usable-results threshold; above this, results are NOT USABLE")
    args = ap.parse_args(argv)

    # Rule 2: the judge must not be the generator.
    gen, judge = os.environ.get("GENERATOR_MODEL"), os.environ.get("JUDGE_MODEL")
    if gen and judge and gen == judge:
        print(f"❌ REFUSING TO RUN: judge model == generator model ({gen}). "
              "A model grading its own output is a mirror, not a signal.", file=sys.stderr)
        return 3

    path = Path(args.cases)
    if not path.exists():
        print(f"no cases file at {path} — add a golden set (see README). Nothing to measure.")
        return 0
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not cases:
        print("cases.jsonl is empty — add real failing cases before trusting any number.")
        return 0

    results = []
    for c in cases:
        try:
            r = evaluate_one(c)
        except Exception as e:  # a crash is a completed-with-failure, counted as such
            r = {"ok": False, "score": None, "precondition": False, "outcome_bad": True, "error": repr(e)}
        results.append(r)

    n = len(results)
    crashed = [r for r in results if not r.get("ok")]
    fail_rate = len(crashed) / n

    # ---- Rule 1: LEAD with the failure count, before any score. ----
    print("=" * 60)
    print(f"EVAL RUN {datetime.now(timezone.utc).isoformat()}")
    print(f"cases: {n} | completed: {n - len(crashed)} | crashed: {len(crashed)} "
          f"| failure-rate: {fail_rate:.0%}")
    usable = fail_rate <= args.fail_rate
    if not usable:
        print(f"❌ RESULTS NOT USABLE — failure rate {fail_rate:.0%} exceeds {args.fail_rate:.0%}. "
              "Do not quote any score below.")
    completed = [r for r in results if r.get("ok") and r.get("score") is not None]
    if completed:
        avg = sum(r["score"] for r in completed) / len(completed)
        label = "avg score (COMPLETED ONLY — not the whole suite)" if not usable else "avg score"
        print(f"{label}: {avg:.2f}  over {len(completed)} completed case(s)")

    # ---- Rule 3: the error-analysis cross-tab, every run. ----
    print("\nerror-analysis cross-tab (precondition × outcome):")
    ct = Counter((r.get("precondition", False), not r.get("outcome_bad", True)) for r in results)
    print("                 outcome GOOD   outcome BAD")
    print(f"  precond OK   :   {ct[(True, True)]:>6}       {ct[(True, False)]:>6}")
    print(f"  precond MISS :   {ct[(False, True)]:>6}       {ct[(False, False)]:>6}")
    print("  (if BAD concentrates in precond-OK, the downstream stage is the problem, not the precondition.)")

    # write results
    outdir = Path(__file__).parent / "results"
    outdir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (outdir / f"eval-{stamp}.json").write_text(json.dumps(
        {"n": n, "failure_rate": fail_rate, "usable": usable, "results": results}, indent=2))
    print(f"\nwrote results/eval-{stamp}.json")

    # CI semantics: non-zero if results are not usable (blocks quoting a bogus number)
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
