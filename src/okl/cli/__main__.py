"""`python -m okl.cli`: the same command line as `okl` and `python -m okl`.

cli.py ran as a script before it became this package (#120); this keeps that working.
"""
from . import main

raise SystemExit(main())
