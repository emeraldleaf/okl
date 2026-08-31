"""`python3 -m okl` — the PATH-independent entry point.

Hooks run in whatever environment the agent harness spawns, which often lacks the
console-script directory on PATH; any python3 that can import okl can still run it.
"""
from .cli import main

raise SystemExit(main())
