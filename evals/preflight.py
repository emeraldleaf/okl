#!/usr/bin/env python3
"""Pre-flight: does every eval task still receive the rule it is testing?

This is the cheap check that would have caught §4d before it cost anything. That change
narrowed interest filtering, silently removed the rate-limiter rule from the briefing, and
the regression only surfaced after 48 model calls and ~25 minutes. Retrieval is
deterministic — whether a record reaches a briefing can be answered in milliseconds, with
no model involved.

Run it before any A/B, and after any change to indexing, filtering, ranking or trimming:

    python3 evals/preflight.py            # exit 1 if any task lost its governing rule

It answers one question per task: is the record this task exists to test actually present
in the briefing the briefed arm would receive? A task whose rule is missing is not
measuring the briefing — it is measuring its absence, and will read as a regression
without saying why.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from okl import core  # noqa: E402
from okl.client import Client, load_config  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# Tasks whose governing rule is KNOWN not to be retrieved, with the reason. An entry here
# is an admission recorded in REPORT.md, not a way to make the check quiet: the task still
# runs, and its result is read as "the briefing without this rule", which is a different
# question from the one the task was written to ask.
ACCEPTED_GAPS = {
    "exit_code_trust": "rule ranks below the top-12 cutoff for this task's wording; "
                       "needs limit>=40 to surface (REPORT.md §4b correction)",
}


def main() -> int:
    tasks = [json.loads(line) for line in (REPO / "evals" / "tasks.jsonl").read_text().splitlines()
             if line.strip()]
    client = Client()
    store = client._local_store()
    # interests=None deliberately: the A/B measures whether a BRIEFING prevents a defect.
    # Interest filtering is a separate mechanism whose job is precision, and inheriting the
    # host repo's interests conflates the two — react_fetch's rule is tagged `react`, which
    # okl does not declare, so that task silently measured its rule's absence. The harness
    # states its own retrieval config rather than distorting okl's to suit the experiment.
    interests = None
    repo = load_config().get("repo") or "okl"

    print(f"pre-flight: {len(tasks)} task(s), interests={interests} (unfiltered by design)\n")
    missing = []
    for t in tasks:
        node = store.get_node(t["defect_node"])
        if node is None:
            missing.append((t["id"], t["defect_node"], "record not in store"))
            continue
        res = core.check(store, repo=repo, task=t["task"], interests=interests)
        present = any(r["id"] == node.id
                      for bucket in ("rules", "relevant_defects", "armed_gates",
                                     "live_retractions", "in_scope_tombstones",
                                     "threat_prior_art", "vocabulary")
                      for r in res.get(bucket, []))
        mark = "ok " if present else "MISSING"
        trimmed = res.get("dropped_by_cutoff", 0)
        print(f"  [{mark}] {t['id']:17} tags={node.tags or '-':28} trimmed={trimmed}")
        if not present:
            missing.append((t["id"], node.id, f"not in briefing (tags={node.tags})"))

    print()
    unexpected = [m for m in missing if m[0] not in ACCEPTED_GAPS]
    for tid in (m[0] for m in missing):
        if tid in ACCEPTED_GAPS:
            print(f"  accepted gap: {tid} — {ACCEPTED_GAPS[tid]}")
    if unexpected:
        print(f"\nPRE-FLIGHT FAILED: {len(unexpected)} task(s) would measure the absence of "
              "their rule:")
        for tid, node, why in unexpected:
            print(f"  {tid}: {node} — {why}")
        print("\nAn A/B run now would read as a regression without saying why. Fix retrieval,")
        print("or add the task to ACCEPTED_GAPS with a reason and record it in REPORT.md.")
        return 1
    print(f"PRE-FLIGHT OK — {len(tasks) - len(missing)}/{len(tasks)} tasks receive the rule "
          f"they test; {len(missing)} accepted gap(s) listed above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
