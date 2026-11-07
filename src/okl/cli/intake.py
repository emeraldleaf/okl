"""`okl intake pr <n>`: a PR's resolved review findings, put to the encoding loop (#376)."""
from __future__ import annotations

import argparse
import sys

from .. import intake
from ..client import Client, OKLUnreachableError


def cmd_intake(args: argparse.Namespace) -> int:
    """List PR `args.number`'s resolved review threads with the commits that resolved them,
    and for each the encoding-loop question and the commands that would encode it.

    It writes nothing: deciding whether a finding is worth a lesson, and saying it as one, is
    the reader's. Exit 0 with the list (empty included), 2 when gh cannot read the PR.
    """
    try:
        pr, files_of = intake.fetch(args.number, args.repo)
        found = intake.findings(pr, files_of)
    except intake.IntakeError as e:
        print(f"okl intake: {e}", file=sys.stderr)
        return 2
    _add_nearest(found)
    print(intake.as_json(found, pr) if args.format == "json" else intake.render(found, pr), end="")
    return 0


def _add_nearest(found: list[intake.Finding]) -> None:
    """Name the lessons a briefing on each finding would show, so one a lesson already covers is
    refined with okl update rather than recorded twice. The briefing, not a raw search: a search
    always returns its best match, and on a finding no lesson covers that named an unrelated one.
    Skipped quietly with no store: the list is still worth having."""
    client = Client()
    if not client.configured:
        return
    for f in found:
        try:
            # Not logged: no agent was briefed, so it is no exposure (`okl metric`).
            result = client.check(f.summary, limit=3, log=False)
        except (OKLUnreachableError, OSError, ValueError) as e:
            # Said, so no finding reads as one nothing covers (CodeRabbit on #388).
            print(f"okl intake: briefing lookup skipped, the store could not be read ({e})",
                  file=sys.stderr)
            return
        titles = {item["id"]: item.get("title", "") for bucket in result.values()
                  if isinstance(bucket, list) for item in bucket
                  if isinstance(item, dict) and item.get("id") and item.get("title")}
        ids = [a["id"] for a in result.get("next_actions", []) if a.get("id")][:3]
        f.briefed = [f"[{i}] {titles.get(i, '')}".rstrip() for i in ids] or None
