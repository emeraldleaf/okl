"""Helpers more than one command group uses."""
from __future__ import annotations

import json
import sys


def _print_json(obj: object) -> None:
    """Dump a result as indented JSON.

    The `--format json` path exists so other tools can consume a check without
    parsing the human briefing, which is markdown and free to change wording.
    """
    json.dump(obj, sys.stdout, indent=2)
    sys.stdout.write("\n")
