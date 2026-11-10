"""`okl changes`: what a change did to the files lessons name, with no model (#398)."""
from __future__ import annotations

import argparse
import sys

from .. import changes
from ..client import Client, OKLRejectedError, OKLUnreachableError
from ..store import backend_errors


def cmd_changes(args: argparse.Namespace) -> int:
    """List the change's new, deleted and renamed files and its moved code, the lessons that
    govern each new file, and a proposed `okl update` for each of this repo's lessons the change
    leaves pointing at the wrong place.

    It writes nothing: each proposal is the reader's to confirm. Exit 0 with the report, empty
    included; 2 when git cannot read the range.
    """
    try:
        found = changes.read(args.base, args.head, args.repo_dir)
    except changes.ChangesError as e:
        print(f"okl changes: {e}", file=sys.stderr)
        return 2
    client = Client()
    nodes = []
    if not client.configured:
        # Opening an unconfigured store creates one (#21), so no lesson is read here.
        print("okl changes: no store is named here, so no lessons are matched (run okl init)", file=sys.stderr)
    else:
        unreadable: tuple[type[Exception], ...] = (OKLUnreachableError, OKLRejectedError, OSError, *backend_errors())
        try:
            nodes = client.all_nodes()
        except unreadable as e:
            print(f"okl changes: lessons skipped, the store could not be read ({e})", file=sys.stderr)
    rep = changes.report(found, nodes, args.repo or client.repo)
    print(changes.as_json(rep) if args.format == "json" else changes.render(rep), end="")
    return 0
