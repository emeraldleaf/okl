"""A receipt names the code that made it, at the start of the run and at the end.

Lesson harness-reads-a-moving-working-tree: a script that runs okl from this checkout reads
whatever the checkout holds while it runs. A branch switch mid-run changes the code behind half
the samples, and a commit read once at the end names code the run may never have used. Past work
broke it five times in scripts that read HEAD once (#300, #307, #309, #312, #363); ab_harness.py
had the fix, and this lends it to every script that writes a receipt. tests/test_eval_guard.py
fails a new receipt writer that does not use it.

    run = run_guard.start()        # before the first sample
    ...
    receipt = run.stamp(receipt)   # just before the receipt is written
"""
from __future__ import annotations

import sys
from typing import Any

import ab_harness as ab

READS = ("src/okl", "evals/*.py")   # okl's code and the eval scripts, not the receipts a run writes


class Run:
    """One run's view of the code: read at its start, compared at its end."""

    def __init__(self) -> None:
        self.started = ab.tree_state(READS)

    def stamp(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Add the commit at the start and at the end; a run whose code moved is not usable, and says so."""
        now = ab.tree_state(READS)
        receipt["okl_commit_at_start"], receipt["okl_commit"] = self.started[0], now[0]
        moved = ab.head_moved(self.started, now)
        if moved:
            receipt["usable"] = False
            receipt["working_tree_moved"] = True
            print(ab.moved_banner(moved), file=sys.stderr)
        return receipt


def start() -> Run:
    """Read the code at the start of a run."""
    return Run()
