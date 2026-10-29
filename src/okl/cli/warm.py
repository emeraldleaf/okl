"""`okl warm`: the local process that keeps the briefing's model loaded (#293, REPORT §4z)."""
from __future__ import annotations

import argparse
import sys

from .. import warm
from ..client import Client


def cmd_warm(args: argparse.Namespace) -> int:
    """start, stop, status, serve (the server itself, in the foreground) or index (this store's
    lesson vectors). Exit 2 when it cannot do what was asked; status exits 1 when none runs."""
    return {"serve": _serve, "stop": _stop, "status": _status, "start": _start, "index": _index}[args.action](args)


def _serve(_args: argparse.Namespace) -> int:
    warm.resume()
    try:
        return warm.serve()
    except warm.WarmUnavailableError as e:
        print(f"NOT SERVING — {e}", file=sys.stderr)
        return 2


def _stop(_args: argparse.Namespace) -> int:
    print(("stopped" if warm.stop() else "no server answered; one still loading or busy exits when it sees the stop")
          + "; it stays off until `okl warm start` or `okl warm index` (`\"warm\": false` keeps it off for good)")
    return 0


def _status(_args: argparse.Namespace) -> int:
    up = warm.ping()
    print(f"running · {up['model']} · pid {up['pid']} · loaded in {up['loaded_s']} s" if up
          else f"not running · `okl warm start` · socket {warm.socket_path()}")
    return 0 if up else 1


def _start(args: argparse.Namespace) -> int:
    warm.resume()
    try:
        up = warm.start(wait_s=args.wait)
    except warm.WarmUnavailableError as e:
        print(f"NOT STARTED — {e}", file=sys.stderr)
        return 2
    print(f"running · {up['model']} · pid {up['pid']}" if up
          else f"starting in the background · log {warm.log_path()}")
    return 0


def _index(_args: argparse.Namespace) -> int:
    """Embed this store's lessons through the running server, starting one if none answers."""
    client = Client()
    if not client.configured or client.mode == "remote":
        print("okl warm index embeds the LOCAL store's lessons; run it where `okl init` ran.", file=sys.stderr)
        return 2
    warm.resume()
    try:
        up = warm.start(wait_s=120)
    except warm.WarmUnavailableError as e:
        print(f"NOT INDEXED — {e}", file=sys.stderr)
        return 2
    if not up:
        print(f"NOT INDEXED — the warm model did not start; see {warm.log_path()}",
              file=sys.stderr)
        return 2
    try:
        report = warm.index(client._local_store())
    except warm.WarmUnavailableError as e:
        print(f"NOT INDEXED — {e}", file=sys.stderr)
        return 2
    print(f"✓ {report['embedded']} lesson(s) embedded, {report['unchanged']} unchanged, "
          f"{report['removed']} removed · {report['model']}")
    if not client._local_store().local:
        print("  this store is a shared database, so the default leaves the model off for it: "
              "set \"warm\": true where you want it (review on #300)")
    return 0
