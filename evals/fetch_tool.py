#!/usr/bin/env python3
"""The when-tool arm's fetch path (REPORT §4ab, #304): an MCP server with one tool, okl_get.

A skill listing says when to open each skill, and Claude Code opens one through a tool whose
description says to call it first. This offers a lesson the same way: the briefing's line says
when the lesson applies, and this tool's description says to read it before writing code when
it does. ab_harness.py starts it per sample with `claude -p --mcp-config`.

Each call is logged to $OKL_SHIM_LOG in the `okl` shim's format ("<rc> show <id>"), so
ab_harness.fetched_ids counts a fetch through this tool exactly as it counts `okl show`: only
one that returned a lesson.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

# The treatment's wording, pre-registered in REPORT §4ab: changing it changes the experiment.
DESCRIPTION = ("Read one lesson the briefing names, in full: what to do, why, and its proof. "
               "Call this before you write code whenever a listed lesson's 'when you see' "
               "matches what you are about to write.")


def okl_get(id: str) -> str:
    """Return the lesson `id` as JSON, and log the call for the harness."""
    from okl.client import Client
    try:
        node: Any = Client().get(id)
    except Exception as e:  # noqa: BLE001 - a failed read is logged as one and reported, never raised
        node, reply = None, f"could not read the lesson ({e})"
    else:
        reply = json.dumps(node, sort_keys=True) if node else f"no lesson with id {id!r}"
    log = os.environ.get("OKL_SHIM_LOG")
    if log:
        with Path(log).open("a", encoding="utf-8") as f:
            f.write(f"{0 if node else 1} show {shlex.quote(id)}\n")
    return reply


def main() -> None:
    """Serve okl_get over stdio."""
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server  # type: ignore[no-redef]  # mcp 1.x
    server = Server("okl")
    server.tool(name="okl_get", description=DESCRIPTION)(okl_get)
    server.run()


if __name__ == "__main__":
    main()
