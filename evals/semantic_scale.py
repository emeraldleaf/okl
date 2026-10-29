#!/usr/bin/env python3
"""How okl.semantic's search scales with the store (REPORT §4q): its own search() over a
SQLite store of N random 512-dimension vectors, with a stub encoder so no model is loaded.

    uv run --no-project --with numpy python3 evals/semantic_scale.py

Writes evals/results/semantic-scale-<stamp>.txt: per N, reading the vectors out of the store,
the search after the read (the matrix product and the top-k), and the pure-Python fallback a
process without numpy runs. The module docstring and docs/COSTS-AND-KNOBS.md quote these, and
tests/test_docs.py holds the docs to this receipt.
"""
from __future__ import annotations

import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from okl import semantic  # noqa: E402
from okl.store import Store  # noqa: E402

DIM = 512
SIZES = (300, 10_000, 50_000)
FALLBACK_UP_TO = 10_000   # the pure-Python product past this takes minutes, and no install runs it


class _Stub:
    """Encodes every text as one fixed unit vector: the model is not what this measures."""

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def encode(self, texts: list[str], normalize: bool = True) -> list[list[float]]:
        return [self.vector for _ in texts]


def _unit(rng: random.Random) -> list[float]:
    v = [rng.gauss(0, 1) for _ in range(DIM)]
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


def _median_ms(fn: Callable[[], object], runs: int) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def main() -> int:
    """Time each size and write the receipt."""
    rng = random.Random(0)  # noqa: S311 - random test vectors, not secrets
    semantic._LOADED[semantic.MODEL_ID] = _Stub(_unit(rng))
    lines = []
    with tempfile.TemporaryDirectory(prefix="okl-scale-") as tmp:
        for n in SIZES:
            store = Store(f"sqlite:///{tmp}/s{n}.db")
            rows = [(f"n{i}", semantic.MODEL_ID, "h", semantic.pack(_unit(rng))) for i in range(n)]
            store._impl.conn.executemany(  # bulk: the insert is not what this measures
                "INSERT INTO embedding(node_id, model, text_hash, vector) VALUES(?,?,?,?)", rows)
            store._impl.conn.commit()
            read = _median_ms(lambda s=store: s.embeddings(semantic.MODEL_ID), 7)
            whole = _median_ms(lambda s=store: semantic.search(s, "a task", 12), 15)
            line = f"  {n:>6,} vectors: read {read:6.1f} ms · search after the read {whole - read:6.2f} ms"
            if n <= FALLBACK_UP_TO:
                saved = sys.modules.get("numpy")
                sys.modules["numpy"] = None  # type: ignore[assignment]  # import numpy raises: the fallback path
                try:
                    slow = _median_ms(lambda s=store: semantic.search(s, "a task", 12), 3)
                finally:
                    if saved is None:
                        del sys.modules["numpy"]
                    else:
                        sys.modules["numpy"] = saved
                line += f" · without numpy {slow - read:7.1f} ms"
            lines.append(line)
            store.close()
    now = datetime.now(UTC)
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=REPO, check=False).stdout.strip()
    head = (f"semantic search scale · {now:%Y-%m-%dT%H:%MZ} · code {commit} · {DIM} dimensions, "
            "okl.semantic.search with a stub encoder, medians")
    out = REPO / "evals" / "results" / f"semantic-scale-{now:%Y%m%d-%H%M}.txt"
    out.write_text("\n".join([head, *lines]) + "\n")
    print("\n".join([head, *lines]) + f"\nreceipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
