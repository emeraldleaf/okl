"""`okl standing`: the lessons this repo names on every task briefing (REPORT §4am)."""
from __future__ import annotations

import argparse
import json
import sys

from .. import core
from ..client import Client, OKLUnreachableError, _find_config
from ..store import RETIRED_STATUSES


def cmd_standing(args: argparse.Namespace) -> int:
    """List this repo's standing lessons, or add or remove some by id.

    They are kept in .okl/config.json as `standing`, and every task briefing in this repo names
    them, one line each. At most core.STANDING_CAP, the number REPORT §4am measured. Exit 2 when
    no config is found here, an id names no lesson, or an add would pass the cap.
    """
    path = _find_config()
    if path is None:
        print("okl standing: no .okl/config.json here or above: run okl init first", file=sys.stderr)
        return 2
    config = json.loads(path.read_text())
    ids = [str(i) for i in config.get("standing") or []]
    client = Client()
    if args.action == "add":
        try:
            missing = [i for i in args.ids if client.get(i) is None]
        except OKLUnreachableError as e:
            print(f"okl standing: the store could not be read ({e})", file=sys.stderr)
            return 2
        if missing:
            print(f"okl standing: no lesson with id {', '.join(missing)}", file=sys.stderr)
            return 2
        wanted = ids + [i for i in dict.fromkeys(args.ids) if i not in ids]
        if len(wanted) > core.STANDING_CAP:
            print(f"okl standing: at most {core.STANDING_CAP} standing lessons (REPORT §4am measured ten); "
                  f"this would make {len(wanted)}. Remove one first.", file=sys.stderr)
            return 2
        ids = wanted
    elif args.action == "remove":
        ids = [i for i in ids if i not in set(args.ids)]
    if args.action in ("add", "remove") and ids != [str(i) for i in config.get("standing") or []]:
        if ids:
            config["standing"] = ids
        else:
            config.pop("standing", None)
        path.write_text(json.dumps(config, indent=2) + "\n")
    _list(client, ids)
    return 0


def _list(client: Client, ids: list[str]) -> None:
    """The standing lessons by id and title; one the store no longer holds is said so."""
    if not ids:
        print("No standing lessons: every task briefing names only what its words match. "
              "Add the ones changes here keep needing: okl standing add <id>...")
        return
    print(f"{len(ids)} standing lesson(s), named on every task briefing in this repo:")
    for i in ids:
        try:
            node = client.get(i)
        except OKLUnreachableError:
            node = None
        title = node.get("title", "") if node else "(not in the store: it is skipped)"
        retired = f" ({node['status']}: it is skipped)" if node and node.get("status") in RETIRED_STATUSES else ""
        print(f"  [{i}] {title}{retired}")
