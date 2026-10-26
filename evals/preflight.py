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

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from okl import core
from okl.client import Client, load_config

REPO = Path(__file__).resolve().parent.parent


# Tasks whose governing rule is KNOWN not to be retrieved, with the reason. An entry here
# is an admission recorded in REPORT.md, not a way to make the check quiet: the task still
# runs, and its result is read as "the briefing without this rule", which is a different
# question from the one the task was written to ask.
# `exit_code_trust` sat here from the §4b correction (its lesson ranked 54th for the task's
# own wording) until the lesson gained a symptom written in the words a developer would use;
# it now ranks 4th (REPORT.md §4o). `ci_linter` since the calibrated decision became the
# default (REPORT.md §4w): its rule clears the line and ranks sixth behind the cap of five,
# and the defect it generalizes, briefed in its place, carries the same fix.
ACCEPTED_GAPS: dict[str, str] = {
    "ci_linter": "under the calibrated default (REPORT §4w) r_pin_gating_tools clears the line "
                 "(four shared subject words) and ranks sixth, behind the cap of five; "
                 "d_unpinned_linter, the defect it generalizes, is briefed with the same fix "
                 "(pin the exact tool version), so the task still measures pinning",
}


def main() -> int:
    """Check each eval task's briefing holds the record it tests; return 1 if one is missing and not an accepted gap."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(REPO / "evals" / "tasks.jsonl"),
                    help="the task file to gate (default: the authored tasks)")
    ap.add_argument("--limit", type=int, default=None, help="gate only the first N tasks, as the harness runs them")
    ap.add_argument("--accept-missing", action="store_true",
                    help="list the tasks whose briefing lacks their governing record and exit 0 anyway: "
                         "for an instrument where that absence is the condition under study (REPORT "
                         "§4r), never for the authored series")
    ap.add_argument("--receipt", action="store_true",
                    help="also write evals/results/preflight-<stamp>.json for REPORT to cite")
    args = ap.parse_args()
    tasks = [json.loads(line) for line in Path(args.tasks).read_text().splitlines() if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    client = Client()
    store = client._local_store()
    # The interests the briefed arm will run with: evals/ab_harness.py passes
    # OKL_BRIEF_INTERESTS to `okl check --interests`, and this gate reads the same variable,
    # so it checks the briefing the run uses and not another one. (It hard-coded unfiltered
    # until 2026-10-22, while receipts ab-20260903-1323 through ab-20261011-2254 ran
    # filtered: react_fetch's rule was absent from the arm and present in the check.)
    # Default empty: unfiltered. The A/B measures whether a BRIEFING prevents a defect;
    # interest filtering is a separate mechanism whose job is precision, and the host
    # repo's interests are not the experiment's — react_fetch's rule is tagged `react`,
    # which okl does not declare, so inheriting them made that task measure its rule's
    # absence (REPORT §4b, §4h).
    interests = brief_interests(os.environ.get("OKL_BRIEF_INTERESTS", ""))
    repo = load_config().get("repo") or "okl"

    shown = ",".join(interests) if interests else "none (unfiltered; set OKL_BRIEF_INTERESTS as the run will)"
    print(f"pre-flight: {len(tasks)} task(s), interests={shown}\n")
    missing = []
    rows = []
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
        rows.append({"task": t["id"], "rule": node.id, "present": present, "trimmed": trimmed})
        if not present:
            missing.append((t["id"], node.id, f"not in briefing (tags={node.tags})"))

    print()
    unexpected = [m for m in missing if m[0] not in ACCEPTED_GAPS]
    for tid in (m[0] for m in missing):
        if tid in ACCEPTED_GAPS:
            print(f"  accepted gap: {tid} — {ACCEPTED_GAPS[tid]}")
    if args.receipt:
        print("receipt:", _write_receipt("preflight", {
            "interests": interests, "tasks": rows,
            "missing": [{"task": m[0], "rule": m[1], "why": m[2]} for m in missing],
            "accepted_gaps": {k: v for k, v in ACCEPTED_GAPS.items()
                              if k in {m[0] for m in missing}},
            "verdict": "FAILED" if unexpected else "OK"}).relative_to(REPO))
    if unexpected and args.accept_missing:
        print(f"\nPRE-FLIGHT: {len(unexpected)} task(s) measure the briefing without their governing "
              "record, accepted by --accept-missing: " + ", ".join(m[0] for m in unexpected))
        return 0
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


def brief_interests(raw: str) -> list[str] | None:
    """The interest list `okl check --interests <raw>` applies: comma-separated, lower-cased, None when empty."""
    return [t.strip().lower() for t in raw.split(",") if t.strip()] or None


def _write_receipt(name: str, body: dict) -> Path:
    """Write evals/results/<name>-<stamp>.json, stamped with the commit it measured.

    Opt-in (--receipt): a REPORT figure needs a committed receipt, but a test runs this
    script too, and a default write would drop a file into the repo on every run.
    """
    def git(*argv: str) -> str:
        return subprocess.run(["git", "-C", str(REPO), *argv], capture_output=True,
                              text=True, check=False).stdout.strip()
    now = datetime.now(UTC)
    receipt = {"measured_at": now.strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": git("rev-parse", "--short", "HEAD"),
               "uncommitted_changes_in_src": bool(git("status", "--porcelain", "--", "src")), **body}
    path = REPO / "evals" / "results" / f"{name}-{now.strftime('%Y%m%d-%H%M')}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
