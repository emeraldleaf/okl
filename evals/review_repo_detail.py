#!/usr/bin/env python3
"""REPORT §4aq's misses and raises, read after the run as its rule requires; not pre-registered.

    python3 evals/review_repo_detail.py
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import realwork_label as rl
import realwork_reach as rr
import review_repo as rp

RECEIPT = rr.REPO / "evals" / "results" / "review-repo-20261109-1827.json"
GRADES = ("act", "minor", "false")


def table(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """How many raises of each kind the judge gave each grade."""
    out: dict[str, Counter] = defaultdict(Counter)
    for kind, grade in pairs:
        out[kind][grade] += 1
    return {kind: {g: c[g] for g in GRADES} for kind, c in sorted(out.items())}


def main() -> int:
    """Write the detail receipt."""
    receipt = json.loads(RECEIPT.read_text())
    rows = {r["pr"]: r for r in receipt["per_task"]}
    tasks = rp.load_tasks()
    labels, states, verdicts, settled = (rp.keyed(n) for n in (rp.LABELS, rp.STATES, rp.VERDICTS, rp.SETTLED))
    answers, text = rp.first_answers(), rp.texts()

    def kind(pr: int, i: str) -> str:
        """The label, or for a lesson labelled needed the state it was sorted into."""
        label = labels.get((pr, i), {}).get("verdict", "unlabelled")
        return label if label != "needed" else f"needed, {states.get((pr, i), {}).get('state', 'unsorted')}"

    by_route, by_kind, raises_per_task = [], [], {}
    for t in tasks:
        pr, acted = t["pr"], 0
        for i in rows[pr]["named"]["review"]:
            first = rp.worst_row(answers, t, i)
            grade = verdicts[(pr, i)]["answer"]
            by_route.append(("first pass said gap" if first["answer"] == "gap" else f"repository read said {settled[(pr, i)]['answer']}", grade))
            by_kind.append((kind(pr, i), grade))
            acted += grade == "act"
        raises_per_task[pr] = {"raised": len(rows[pr]["named"]["review"]), "act": acted, "calling_for_action": len(rows[pr]["needed"])}

    misses = []
    for t in tasks:
        for i in rows[t["pr"]]["missed"]:
            first = rp.worst_row(answers, t, i)
            misses.append({"pr": t["pr"], "lesson": i, "first_pass": first["answer"], "repository_read": settled.get((t["pr"], i), {}).get("answer"),
                           "sorted_as": states[(t["pr"], i)]["state"], "reason": states[(t["pr"], i)]["why"], "change_chars": len(rp.change_of(t))})

    def rule(name: str, raises: Callable[[dict, str], bool]) -> dict:
        """Reach and raises had the review raised on `raises` instead."""
        all_raised = sum(1 for t in tasks for i in t["lessons"] if i in text and raises(t, i))
        hit = sum(1 for t in tasks for i in rows[t["pr"]]["needed"] if i in text and raises(t, i))
        total = sum(len(r["needed"]) for r in rows.values())
        return {"rule": name, "raised": all_raised, "calling_for_action_raised": hit, "of": total, "reach": round(hit / total, 3)}

    def said(t: dict, i: str) -> str:
        row = rp.worst_row(answers, t, i)
        return row["answer"] if row else ""

    confirmed = Counter(verdicts[(pr, i)]["answer"] for pr, r in rows.items() for i in r["confirmed"])
    act_counts = [v["act"] for v in raises_per_task.values()]
    out = {"section": "4aq misses and raises, not pre-registered", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": rl.git("rev-parse", "HEAD").strip(),
           "status": "model-judged, not yet audited (#394)", "from_receipt": RECEIPT.name, "misses": misses,
           "missed_by_first_pass": dict(Counter(m["first_pass"] for m in misses)), "missed_by_sorted_state": dict(Counter(m["sorted_as"] for m in misses)),
           "missed_after_repository_read": dict(Counter(m["repository_read"] for m in misses if m["repository_read"])),
           "needed_pairs_by_state": dict(Counter(states.get((t["pr"], i), {}).get("state", "unsorted") for t in tasks for i in t["lessons"] if labels.get((t["pr"], i), {}).get("verdict") == "needed")),
           "grades_by_route": table(by_route), "grades_by_kind": table(by_kind), "grades_on_raises_the_sheet_counts": {g: confirmed[g] for g in GRADES},
           "other_raising_rules": [rule("first pass gap only", lambda t, i: said(t, i) == "gap"),
                                   rule("first pass gap or ask, no repository read", lambda t, i: said(t, i) in ("gap", "ask")),
                                   rule("gap from either step, dropping what stays ask", lambda t, i: said(t, i) == "gap" or (said(t, i) == "ask" and settled.get((t["pr"], i), {}).get("answer") == "gap"))],
           "tasks": {"total": len(tasks), "raised_nothing": sum(1 for v in raises_per_task.values() if not v["raised"]), "at_least_one_act": sum(1 for a in act_counts if a), "act_median": statistics.median(act_counts),
                     "no_action_but_raised": sum(1 for v in raises_per_task.values() if v["raised"] and not v["calling_for_action"]),
                     "raises_on_those": sum(v["raised"] for v in raises_per_task.values() if v["raised"] and not v["calling_for_action"])}}
    dest = rr.REPO / "evals" / "results" / f"review-repo-detail-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "misses"}, indent=1))
    print(f"receipt: {dest.relative_to(rr.REPO)}")
    for m in misses:
        print(f"#{m['pr']} {m['lesson']} first={m['first_pass']} read={m['repository_read']} sorted={m['sorted_as']}\n    {m['reason'][:420]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
