"""`okl serve` and `okl mcp`: the long-running HTTP and MCP servers, behind their extras."""
from __future__ import annotations

import argparse


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the shared HTTP service.

    The 0.0.0.0 default is so the service is reachable from outside its container,
    which is the only way a shared instance is useful. OKL_TOKEN gates every route
    except /health; see docs/DEPLOY.md before exposing it.
    """
    from ..service import run
    run(host=args.host, port=args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the MCP tool surface over stdio, for a coding agent to call.

    Same operations as the CLI through the same Client, so remote/local mode and the
    fail-closed behaviour are identical whichever surface the agent uses.
    """
    from ..mcp_server import run_stdio
    run_stdio()
    return 0
