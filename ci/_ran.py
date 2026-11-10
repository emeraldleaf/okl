"""A check that crashed did not run: exit 2, never the 1 that means it found something.

Lessons n_e7988ff536fb (exit codes are this CLI's public API) and n_5ddb0776a863 (a gate that read
nothing must not pass). Six of these checks, run where their inputs were missing, raised and exited
1, so "could not read README.md" read as a finding (found by tests/test_exit_codes.py's sweep). Each
check installs this when it runs as a script; loaded by a test as a module, it does not, so a
test process keeps its own hook.
"""
import os
import sys
from pathlib import Path


def install() -> None:
    """Make any uncaught exception print its traceback and exit 2."""
    def did_not_run(kind, value, tb) -> None:  # noqa: ANN001 - sys.excepthook's own signature
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        sys.stdout.flush()
        sys.__excepthook__(kind, value, tb)
        print(f"{Path(sys.argv[0]).name}: could not run (exit 2, not a finding)", file=sys.stderr)  # noqa: T201
        sys.stderr.flush()
        os._exit(2)

    sys.excepthook = did_not_run
