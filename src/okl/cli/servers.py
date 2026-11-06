"""`okl serve` and `okl mcp`: the long-running HTTP and MCP servers, behind their extras."""
from __future__ import annotations

import argparse
import importlib
import ipaddress
import os
import sys


def _open_bind_refusal(host: str, allow_no_token: bool) -> str | None:
    """Why `okl serve` must not start on `host`, or None when it may.

    With no OKL_TOKEN every route is open, GET /nodes included. On loopback only this
    machine can reach it; anywhere else the whole store goes to whoever can reach the
    port, and nothing used to warn or refuse (#371). An empty token is no token: the
    service treats it as unset, and compose's `${OKL_TOKEN:-}` hands a process exactly that.
    OKL_ALLOW_NO_TOKEN=1 is the flag's environment form, the one `module:app` reads.
    """
    if (os.environ.get("OKL_TOKEN") or allow_no_token or os.environ.get("OKL_ALLOW_NO_TOKEN") == "1"
            or _is_loopback(host)):
        return None
    return (f"OKL: refusing to serve on {host} without OKL_TOKEN: every route, GET /nodes "
            "included, would be open to anyone who can reach the port. Set OKL_TOKEN, bind "
            "--host 127.0.0.1, or pass --allow-no-token (OKL_ALLOW_NO_TOKEN=1) when a proxy "
            "in front authenticates (docs/DEPLOY.md §2).")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False   # any other name may resolve to an address others can reach


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the shared HTTP service.

    The 0.0.0.0 default is so the service is reachable from outside its container,
    which is the only way a shared instance is useful. OKL_TOKEN gates every route
    except /health; see docs/DEPLOY.md before exposing it. Exit 2 when the host is not
    loopback and no token is set (unless --allow-no-token), checked before anything is
    imported or bound, and exit 2, naming the extra to install, when FastAPI or uvicorn
    is missing.
    """
    refusal = _open_bind_refusal(args.host, args.allow_no_token)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    try:
        from ..service import run  # raises RuntimeError naming the extra without FastAPI
    except RuntimeError as e:
        print(f"OKL: {e}", file=sys.stderr)
        return 2
    try:
        importlib.import_module("uvicorn")   # imported here only to fail before serving
    except ImportError:
        print("OKL: okl serve needs uvicorn: install 'observed-knowledge-ledger[service]'",
              file=sys.stderr)
        return 2
    run(host=args.host, port=args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the MCP tool surface over stdio, for a coding agent to call.

    Same operations as the CLI through the same Client, so remote/local mode and the
    fail-closed behaviour are identical whichever surface the agent uses. Exit 2, naming
    the cause, when the MCP SDK is missing or has no server class okl knows.
    """
    from ..mcp_server import _build
    # Build first, then serve: only a failure to build means "could not run". A
    # RuntimeError while serving is not this, so it is not caught here.
    try:
        server = _build()
    except RuntimeError as e:
        print(f"OKL: {e}", file=sys.stderr)
        return 2
    server.run()
    return 0
