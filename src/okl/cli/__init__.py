"""The `okl` command line: one module per thing you do with it.

Where to look:

    parser.py        every command and flag, in one table (start here)
    install.py       okl init / connect / scaffold: wiring okl into a repo, and removing it
    lessons.py       okl check / record / link / search / bootstrap / dedup
    packs.py         okl seed, and the bundled seed packs that init offers
    verification.py  okl verify / reverify / drift / export: proving lessons, finding stale ones
    health.py        okl doctor / metric / coverage: reports on the install and the store
    servers.py       okl serve / mcp: the long-running HTTP and MCP servers
    common.py        _print_json, the JSON printer three of the above share

A leading underscore marks a helper as private to this package, not to one module: the
first-run helpers in packs.py are used by install.py and lessons.py too.

Every command is a `cmd_<name>(args) -> int` handler, and the int is the exit code: 0
ran clean, 1 ran and found something, 2 could not run. okl runs inside other people's
hooks and CI, where the exit code is the only thing read.

Stdlib argparse only, so the package installs with zero required dependencies;
`serve` and `mcp` import their extras lazily.
"""
from __future__ import annotations

import sys

from ..client import OKLUnreachableError
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch, converting store errors into exit codes.

    The backstop matters more than it looks: this CLI runs inside other people's hooks
    and CI, where the exit code is the only thing read. No command may answer a
    rejected or unreachable store with a traceback and a zero exit.
    """
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OKLUnreachableError) as e:
        # The backstop, so no command can ever answer a rejected or unreachable service
        # with a Python traceback. Commands that can say something more specific catch
        # these themselves and never reach here; this exists so the ones that do not —
        # and the ones added later — still exit non-zero with a line a human can act on.
        print(f"OKL: {e}", file=sys.stderr)
        return 2
