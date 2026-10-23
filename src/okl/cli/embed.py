"""`okl embed`: build or refresh the local store's vectors for `--hybrid` briefings (#258)."""
from __future__ import annotations

import argparse
import sys

from .. import semantic
from ..client import Client


def cmd_embed(args: argparse.Namespace) -> int:
    """Embed every record whose text changed; exit 2 when the extra or the model is missing."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — run `okl init` here first.", file=sys.stderr)
        return 2
    if client.mode == "remote":
        print("okl embed builds the LOCAL store's vectors; a shared service keeps its own.", file=sys.stderr)
        return 2
    try:
        report = semantic.build_index(client._local_store(), model_id=args.model)
    except semantic.SemanticUnavailableError as e:
        print(f"NOT EMBEDDED — {e}", file=sys.stderr)
        return 2
    print(f"✓ {report['embedded']} record(s) embedded, {report['unchanged']} unchanged, "
          f"{report['removed']} removed · {report['model']}"
          + (f" ({report['dim']} dims)" if report["dim"] else ""))
    return 0
