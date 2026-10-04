#!/usr/bin/env python3
"""How many tokens does a briefing cost? The receipt behind every size the docs quote.

The README and the MCP `okl_check` description each quoted a size for the briefing, and
the two disagreed (~1,650 and ~2,300 for the same full briefing), because each was
measured once, at a different time, against a different store. This measures them all in
one run, on one store, so they can be quoted together:

    python3 evals/briefing_size.py        # writes evals/results/briefing-size-<stamp>.json

Method: a fresh store in a temp folder, holding every bundled seed pack and nothing else,
no interest filter, and one representative task. A briefing is measured as the text that
reaches the model (for the hook format, its additionalContext), and tokens are
characters / 4, rounded to the nearest 10: a rough rule, not a tokenizer, so the figures
are for comparing sizes, not for billing. No model is called.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASK = "add an endpoint that returns an order for the logged-in user"
LIMITS = (3, 5, 8, 12)


def _okl(argv: list[str], cwd: Path, env: dict[str, str]) -> str:
    """Run this checkout's okl (not whatever `okl` is on PATH) and return its stdout."""
    r = subprocess.run([sys.executable, "-m", "okl", *argv], cwd=cwd, env=env,
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit(f"okl {' '.join(argv)} exited {r.returncode}:\n{r.stderr}")
    return r.stdout


def _tokens(text: str) -> int:
    """Characters / 4, to the nearest 10."""
    return int(round(len(text) / 4, -1))


def main() -> int:
    """Build the store, brief the task in each shape, and write the receipt."""
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout.strip()
    # The receipt names a commit, so say when the code measured was not that commit's.
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=REPO,
                                capture_output=True, text=True, check=True).stdout.strip())
    with tempfile.TemporaryDirectory() as tmp:
        where = Path(tmp)
        # Only what a fresh install has: no shared service, no inherited database, and a
        # HOME of its own so nothing from this machine's config reaches the store.
        env = {k: v for k, v in os.environ.items()
               if k not in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN")}
        env.update(HOME=str(where), PYTHONPATH=str(REPO / "src"))
        subprocess.run(["git", "init", "-q", "."], cwd=where, check=True)
        _okl(["init", "--repo", "measure", "--no-claude", "--no-seed", "--no-ci"], where, env)
        _okl(["seed", "--all"], where, env)
        with sqlite3.connect(where / ".okl" / "okl.db") as db:
            records = db.execute("SELECT count(*) FROM node").fetchone()[0]

        def brief(*flags: str) -> str:
            out = _okl(["check", "--task", TASK, "--interests", "", *flags], where, env)
            if "hook" in flags:
                return str(json.loads(out)["hookSpecificOutput"]["additionalContext"])
            return out

        sizes = {
            "full (agent format, default --limit 12)": brief(),
            "hook format, default --limit 12": brief("--format", "hook"),
            **{f"compact, --limit {n}": brief("--format", "hook", "--compact", "--limit", str(n))
               for n in LIMITS},
            **{f"--format actions --limit {n}": brief("--format", "actions", "--limit", str(n))
               for n in LIMITS},
        }

    receipt = {
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "okl_commit": commit,
        "uncommitted_changes_in_src": dirty,
        "store": f"fresh, every bundled seed pack: {records} records, no interest filter",
        "task": TASK,
        "method": "tokens = characters / 4, to the nearest 10; the text that reaches the model",
        "briefings": {name: {"characters": len(text), "tokens": _tokens(text)}
                      for name, text in sizes.items()},
    }
    out = REPO / "evals" / "results" / f"briefing-size-{datetime.now(timezone.utc):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    for name, size in receipt["briefings"].items():
        print(f"{size['tokens']:>6,} tokens  {name}")
    print(f"\n{records} records, okl {commit}. Receipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
