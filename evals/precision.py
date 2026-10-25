#!/usr/bin/env python3
"""Precision check: how much does a briefing carry when the prompt has no subject? (R8, #179)

The pre-flight checks recall (does each eval task still receive its rule) and the A/B
checks outcomes on 8 bait tasks. Nothing measured the other side: a prompt like "ok go"
or "what about this one?" was briefed 12 lessons, the cap, and nobody counted it.

This scores filler prompts with no labels needed. Each should brief nothing, or at most
FILLER_BUDGET lessons. It also reports how often briefings hit the cap and which lessons
take the most slots. It runs on a store built only from the committed seed packs in
seed/, never on a copy of a live store: a live store can name private repos, and its
contents differ from machine to machine. okl's own repo lessons can join once R19 (#186)
commits them.

    python3 evals/precision.py             # exit 1 if a filler prompt is over budget
    python3 evals/precision.py --receipt   # also write evals/results/precision-<stamp>.json
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from okl.client import Client

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

FILLER_BUDGET = 3
# What people type between real tasks: replies, go-aheads and questions about the last
# answer. Single content words ("merge", "published") are left out on purpose: they can
# name a subject, and a lesson about merge commits may well apply to "merge".
FILLER = ["ok", "k", "yes", "no", "sure", "thanks", "thank you", "ok thanks", "ok go",
          "go ahead", "do it", "yes do it", "ok do that", "keep going", "continue", "next",
          "ok whats next", "what's next", "ok now what", "sounds good", "looks good", "lgtm",
          "what about this one?", "done?", "why?", "hmm", "try again", "is it done?",
          "can you do that?", "let's do it"]


def _seed_packs() -> list[Path]:
    """The seed packs git tracks. A glob took any JSON in seed/, so an untracked pack
    changed the result while the receipt named a clean commit (review of #196)."""
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "seed/*.json"],
                             capture_output=True, text=True, check=True).stdout.split()
    return [REPO / p for p in sorted(tracked)]


def _seeded_client(workdir: Path) -> Client:
    """A client on a store in `workdir` holding exactly the tracked seed packs."""
    from okl.client import Client
    from okl.seed import seed_from_file
    (workdir / ".okl").mkdir()
    (workdir / ".okl" / "config.json").write_text(json.dumps({"repo": "okl"}))
    os.chdir(workdir)
    client = Client()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        for pack in _seed_packs():
            seed_from_file(client, str(pack))
    return client


def _okl_commit() -> str | None:
    out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip() or None
    # seed/ too: an edited pack changes what is measured as surely as edited code does.
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "src", "seed"],
                           capture_output=True, text=True).stdout.strip()
    return f"{out}+dirty" if out and dirty else out


def measure(client: Client, limit: int = 12) -> dict:
    """Briefing sizes for the filler prompts and the eval tasks, with per-lesson shares."""
    def briefed(task: str) -> list[str]:
        from okl import core
        return core.briefed_ids(client.check(task, limit=limit))

    filler = {p: briefed(p) for p in FILLER}
    tasks = [json.loads(line) for line in (REPO / "evals" / "tasks.jsonl").read_text().splitlines()
             if line.strip()]
    bait = {t["id"]: briefed(t["task"]) for t in tasks}
    share = Counter(i for ids in [*filler.values(), *bait.values()] for i in ids)
    return {
        "store_records": len(client.all_nodes()),
        "limit": limit,
        "filler_budget": FILLER_BUDGET,
        "filler": {p: len(ids) for p, ids in filler.items()},
        "filler_over_budget": sorted(p for p, ids in filler.items() if len(ids) > FILLER_BUDGET),
        "filler_cap_hits": sum(len(ids) >= limit for ids in filler.values()),
        "bait": {t: len(ids) for t, ids in bait.items()},
        "bait_cap_hits": sum(len(ids) >= limit for ids in bait.values()),
        "top_lessons": share.most_common(8),
    }


def main() -> int:
    """Score the filler prompts on a seed-only store; exit 1 when one is over budget."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", action="store_true",
                    help="also write evals/results/precision-<stamp>.json for REPORT to cite")
    args = ap.parse_args()
    # These briefings reach no agent: logging them would count as exposure (#129).
    os.environ["OKL_BRIEFING_LOG"] = "0"
    for var in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        os.environ.pop(var, None)   # never a live store, whatever the shell exported
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="okl-precision-") as tmp:
        try:
            report = measure(_seeded_client(Path(tmp)))
        finally:
            os.chdir(cwd)
    report["okl_commit"] = _okl_commit()
    for prompt, n in report["filler"].items():
        print(f"  {'OVER' if n > FILLER_BUDGET else 'ok  '} {n:2}  {prompt!r}")
    print(f"filler prompts over budget ({FILLER_BUDGET}): {len(report['filler_over_budget'])} "
          f"of {len(FILLER)}; at the cap: {report['filler_cap_hits']}")
    print(f"bait tasks at the cap: {report['bait_cap_hits']} of {len(report['bait'])}")
    print("lessons taking the most slots:", ", ".join(f"{i} ({n})" for i, n in report["top_lessons"][:5]))
    if args.receipt:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
        out = REPO / "evals" / "results" / f"precision-{stamp}.json"
        out.write_text(json.dumps(report, indent=1) + "\n")
        print(f"wrote {out.relative_to(REPO)}")
    ok = not report["filler_over_budget"]
    print("PRECISION OK" if ok else "PRECISION OVER BUDGET")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
