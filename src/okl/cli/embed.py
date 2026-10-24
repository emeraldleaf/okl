"""`okl embed`: build or refresh the local store's vectors for `--hybrid` briefings (#258)."""
from __future__ import annotations

import argparse
import sys

from .. import rerank, semantic
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
    embedded = True
    try:
        # One model, semantic.MODEL_ID: check searches that model's vectors and no other, so a
        # choice here would write vectors nothing reads (review on #267).
        report = semantic.build_index(client._local_store())
    except semantic.SemanticUnavailableError as e:
        # Not a return: the two stages are independent, and an install with only the rerank
        # extra still needs this command to cache its model (review on #271).
        print(f"NOT EMBEDDED — {e}", file=sys.stderr)
        embedded = False
    else:
        print(f"✓ {report['embedded']} record(s) embedded, {report['unchanged']} unchanged, "
              f"{report['removed']} removed · {report['model']}"
              + (f" ({report['dim']} dims)" if report["dim"] else ""))
    # The reranker needs no index, only its model in the cache; this is its one online step.
    try:
        rerank.load_model(offline=False)
        print(f"✓ reranker {rerank.MODEL_ID} cached for `okl check --rerank`")
    except rerank.RerankUnavailableError as e:
        print(f"  reranker not set up ({e})")
    return 0 if embedded else 2
