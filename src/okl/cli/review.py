"""`okl review`: a model reads each lesson nothing re-checks against the repo (#315, REPORT §4ai).

Opt-in and outside the loop: it runs only when the person runs it, asks before the first model
call, and never writes. Each lesson it questions is reported with the words that no longer
hold, for the person to confirm and then `okl update` or `okl retire`.
"""
from __future__ import annotations

import argparse
import shlex
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import review
from ..client import Client, OKLUnreachableError
from .common import _print_json

if TYPE_CHECKING:
    from ..store import Node

# The measured catch rates, as the help and every report state them.
MEASURED_LINE = (f"Measured with the default judge (REPORT §4ai): it caught {review.MEASURED['planted'][0]} of "
                 f"{review.MEASURED['planted'][1]} planted wrong details and questioned "
                 f"{review.MEASURED['over_called'][0]} of {review.MEASURED['over_called'][1]} lessons known to be "
                 "current, so confirm each verdict before you act on it.")
_ORDER = {v: i for i, v in enumerate(("stale", "outlived", "detail wrong"))}


def _targets(args: argparse.Namespace) -> list[Node] | int:
    """The lessons to judge, the named ones or every unchecked one, or the exit code to stop with."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — nothing to review. Run `okl init` first.", file=sys.stderr)
        return 2
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot review.\n{e}", file=sys.stderr)
        return 2
    if not args.node_id:
        return review.unchecked(nodes)
    by_id = {n.id: n for n in nodes}
    if missing := [i for i in args.node_id if i not in by_id]:
        print(f"okl review: no lesson with id {', '.join(missing)}", file=sys.stderr)
        return 2
    return [by_id[i] for i in args.node_id]


def _judge(args: argparse.Namespace, count: int) -> list[str] | int:
    """The judge command, once the person has agreed to run it, or the exit code to stop with:
    the measured judge unless --judge names another, and a model call is never made unasked."""
    try:
        judge = shlex.split(args.judge) if args.judge else list(review.JUDGE)
    except ValueError as e:   # an unbalanced quote: say so and stop, never a traceback
        print(f"okl review: cannot read --judge: {e}", file=sys.stderr)
        return 2
    if not judge or shutil.which(judge[0]) is None:
        print(f"okl review: the judge `{judge[0] if judge else ''}` is not on PATH. The default is Claude "
              "Code's CLI; pass --judge '<a command that reads the prompt on stdin and prints its "
              "answer>' for another", file=sys.stderr)
        return 2
    print(f"okl review will run {count} judge session(s), one per lesson, each up to "
          f"{args.timeout} seconds, with:\n  {shlex.join(judge)}", file=sys.stderr)
    if args.yes:
        return judge
    if not sys.stdin.isatty():
        print("refusing to call a model unattended: pass --yes to run it", file=sys.stderr)
        return 2
    return judge if input("Run it? [y/N] ").strip().lower() in ("y", "yes") else 2


def _print_report(results: list[dict[str, Any]], measured: bool) -> None:
    """The questioned lessons with their quoted words, then the counts and what to do next."""
    questioned = sorted((r for r in results if r.get("verdict") in review.QUESTIONED),
                        key=lambda r: (_ORDER[r["verdict"]], r["id"]))
    for r in questioned:
        print(f"[{r['id']}] {r['verdict'].upper()} · {r['title']}")
        print(f"    no longer holds: \"{r['no_longer']}\"")
        print(f"    the repository has: {r['instead']}")
        if r.get("evidence"):
            print(f"    evidence: {', '.join(map(str, r['evidence']))}")
    counts = {v: sum(1 for r in results if r.get("verdict") == v) for v in review.VERDICTS}
    counts["no answer"] = sum(1 for r in results if not r.get("verdict"))
    print(("\n" if questioned else "") + f"okl review: {len(results)} judged — "
          + ", ".join(f"{n} {v}" for v, n in counts.items() if n))
    for r in results:
        if not r.get("verdict"):
            print(f"    no answer for [{r['id']}]: {r['error']}", file=sys.stderr)
    if questioned:
        print("Each verdict is the judge's reading, not a fact. Check it, then correct the lesson with "
              "`okl update <id>` (a fixed defect stays recorded), or `okl retire <id> --reason ...` "
              "if it no longer applies.")
    print(MEASURED_LINE if measured else
          "This is not the judge §4ai measured: its catch rates hold for the default judge alone.")


def _exit_code(results: list[dict[str, Any]]) -> int:
    """1 when a lesson was questioned; else 2 when one got no answer, since a lesson the judge
    did not answer for was not reviewed and is never a clean exit (fail closed); else 0."""
    if any(r.get("verdict") in review.QUESTIONED for r in results):
        return 1
    return 2 if any(not r.get("verdict") for r in results) else 0


def cmd_review(args: argparse.Namespace) -> int:
    """Judge the lessons nothing re-checks against the repo at HEAD, and report the ones questioned.

    Exit 1 when the judge questioned at least one lesson; otherwise 2 when it could not run or
    gave no answer for a lesson, and 0 when it answered for every lesson and questioned none.
    Nothing is written: the person decides what each verdict is worth.
    """
    from .verification import _snapshot_path
    targets = _targets(args)
    if isinstance(targets, int):
        return targets
    if not targets:
        print("okl review: every lesson recorded here has a check or governed files; nothing to review.")
        return 0
    if args.list:
        for n in targets:
            print(f"[{n.id}] {n.type} · {n.title}")
        print(f"\n{len(targets)} lesson(s) to review. Run `okl review --yes` to judge them.", file=sys.stderr)
        return 0
    judge = _judge(args, len(targets))
    if isinstance(judge, int):
        return judge
    done = []

    def progress(r: dict[str, Any]) -> None:
        done.append(r)
        print(f"  {len(done)}/{len(targets)} {r.get('verdict') or 'no answer':12} {r['id']}", file=sys.stderr)
    try:
        results = review.review(targets, Path(_snapshot_path().parent), judge=judge, workers=args.workers,
                                timeout=args.timeout, progress=progress)
    except ValueError as e:
        print(f"okl review: {e}", file=sys.stderr)
        return 2
    measured = judge == review.JUDGE
    if args.format == "json":
        _print_json({"judge": shlex.join(judge), "measured": measured, "lessons": results})
    else:
        _print_report(results, measured)
    return _exit_code(results)
