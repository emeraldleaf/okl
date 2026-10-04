"""`okl serve` and `okl mcp`: the long-running HTTP and MCP servers, behind their extras."""
from __future__ import annotations

import argparse
import importlib
import sys


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the shared HTTP service.

    The 0.0.0.0 default is so the service is reachable from outside its container,
    which is the only way a shared instance is useful. OKL_TOKEN gates every route
    except /health; see docs/DEPLOY.md before exposing it. Exit 2, naming the extra to
    install, when FastAPI or uvicorn is missing.
    """
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
