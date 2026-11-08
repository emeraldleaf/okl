#!/usr/bin/env python3
"""Missed lessons: each lesson that applied to real work and did not reach the agent, replayed.

Every case in evals/missed_lessons.jsonl is a lesson the store held that a session needed and
was not briefed on, with the text that existed at the time: the prompt as typed, the reply the
prompt hook could have read with it, the issue the work came from, and the agent's own words
at the commit (a docstring written then). Nothing is reworded after the fact, because a query
written by someone who knows the miss is a query that finds it.

For each case, each query and each retrieval arm okl ships, it prints whether the lesson was
shown in full, named in a line, or absent, and the files it would have been briefed on by
path. It calls no model and writes nothing (OKL_BRIEFING_LOG=0).

    python3 evals/missed_lessons.py              # the table; exit 1 if the default arm misses a case,
                                                 # 2 if any text and arm pair did not run
    python3 evals/missed_lessons.py --receipt    # also write evals/results/missed-<date>.txt
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = REPO / "evals" / "missed_lessons.jsonl"
# The retrieval arms okl ships: the decision, and the semantic arm beside the full-text search.
ARMS: list[tuple[str, list[str]]] = [
    ("tiered (default)", ["--decision", "tiered", "--hybrid", "off", "--warm", "off"]),
    ("floor", ["--decision", "floor", "--hybrid", "off", "--warm", "off"]),
    ("tiered+hybrid", ["--decision", "tiered", "--hybrid", "linear", "--warm", "off"]),
    ("floor+hybrid", ["--decision", "floor", "--hybrid", "linear", "--warm", "off"]),
    ("tiered+warm", ["--decision", "tiered", "--hybrid", "off", "--warm", "on"]),
    ("floor+warm", ["--decision", "floor", "--hybrid", "off", "--warm", "on"]),
]
FULL = ("next_actions", "armed_gates", "relevant_defects", "live_retractions", "in_scope_tombstones",
        "threat_prior_art", "rules", "vocabulary", "decisions", "context", "stale_warnings")


def _okl(*args: str) -> dict:
    """`okl check ... --format json` from this checkout, unlogged; {} when it fails. A semantic arm
    that did not run (the warm model missed its budget, as under load) is asked once more."""
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "OKL_BRIEFING_LOG": "0"}
    result: dict = {}
    for _attempt in range(2):
        r = subprocess.run([sys.executable, "-m", "okl", "check", *args, "--format", "json"],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
        try:
            result = json.loads(r.stdout)
        except json.JSONDecodeError:
            return {}
        if not unavailable(result):
            return result
    return result


def where(result: dict, lesson: str) -> str:
    """'full', 'line' or '-' for `lesson` in a briefing result; '?' if the arm did not run."""
    if not result:
        return "?"
    if any(isinstance(i, dict) and i.get("id") == lesson for k in FULL for i in result.get(k) or []):
        return "full"
    if any(isinstance(i, dict) and i.get("id") == lesson for i in result.get("also_matched") or []):
        return "line"
    return "-"


def ranks(text: str, lesson: str) -> str:
    """Where `lesson` ranks among every candidate, before any floor or cap: by the full-text
    search alone, and fused with the local embedding (potion). How far off a miss was."""
    sys.path.insert(0, str(REPO / "src"))
    from okl import core
    from okl.client import Client
    store = Client()._local_store()
    out = []
    for label, hybrid in (("lexical", None), ("lexical+potion", "linear")):
        ids = [n.id for n in core.ranked_candidates(store, text, 1000, hybrid).nodes]
        out.append(f"{label} {ids.index(lesson) + 1} of {len(ids)}" if lesson in ids
                   else f"{label} not a candidate ({len(ids)} found)")
    return " · ".join(out)


def unavailable(result: dict) -> str:
    """Why an asked-for semantic arm did not run, if it did not."""
    return "; ".join(str(result[k]) for k in ("hybrid_unavailable", "warm_unavailable") if result.get(k))


def main() -> int:
    """Print the table; exit 1 if the default arm misses any case at any query."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", action="store_true", help="also write evals/results/missed-<date>.txt")
    args = ap.parse_args()
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                          text=True).stdout.strip()
    lines = [f"missed lessons replay · {datetime.now(UTC):%Y-%m-%dT%H:%MZ} · okl at {head}",
             "full = shown in full · line = named in one line · - = absent · ? = arm did not run", ""]
    notes: set[str] = set()
    default_misses = []
    for case in cases:
        lines.append(f"[{case['id']}] lesson {case['lesson']}")
        width = max(len(q) for q in case["queries"])
        lines.append(" " * (width + 4) + " | ".join(f"{name:>16}" for name, _ in ARMS))
        for qname, text in case["queries"].items():
            cells = []
            for name, flags in ARMS:
                result = _okl("--task", text, *flags)
                why = unavailable(result)
                if why:
                    notes.add(f"{name}: {why}")
                cell = "?" if why else where(result, case["lesson"])
                cells.append(cell)
                if name.startswith("tiered (default)") and cell == "-":
                    default_misses.append((case["id"], qname))
            lines.append(f"    {qname:<{width}} " + " | ".join(f"{c:>16}" for c in cells))
        lines.extend(f"    by path {path}: {where(_okl('--path', path), case['lesson'])}"
                     for path in case.get("paths", []))
        lines.append("    rank among every candidate, before the floor and the cap:")
        lines.extend(f"      {qname:<{width}} {ranks(text, case['lesson'])}"
                     for qname, text in case["queries"].items())
        lines.append("")
    lines += [f"note: {n}" for n in sorted(notes)]
    lines.append(f"default arm misses: {len(default_misses)} of "
                 f"{sum(len(c['queries']) for c in cases)} case queries")
    unrun = sum(line.count(" ? ") + line.endswith(" ?") for line in lines if " | " in line)
    if unrun:
        # A pair that did not run is a gap, not a miss: the run says so at the top of its verdict.
        lines.append(f"NOT USABLE: {unrun} text and arm pair(s) did not run (see the notes); "
                     "no claim may cover them")
    out = "\n".join(lines) + "\n"
    print(out, end="")
    if args.receipt:
        path = REPO / "evals" / "results" / f"missed-{datetime.now(UTC):%Y%m%d-%H%M}.txt"
        path.write_text(out)
        print(f"receipt: {path.relative_to(REPO)}")
    if unrun:
        return 2
    return 1 if default_misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
