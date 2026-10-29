#!/usr/bin/env python3
"""What each model okl can load puts on disk: its own loader, run against an empty cache, and
the files it fetched, counted once each (a hub cache links snapshots to blobs).

    uv run --no-project --with model2vec --with fastembed python3 evals/model_files.py

Writes evals/results/model-files-<stamp>.txt. Each model is downloaded once into a temporary
directory, measured and deleted; one whose extra is not installed is listed as not measured.
The docs quote these sizes, and tests/test_docs.py holds them to this receipt: "249 MB" and
"about 80 MB" were quoted for years from a repository listing and a guess, not from what the
loader fetches (review on #300).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# What to load, as okl loads it: the module's own loader, online, into the cache the
# environment below points at.
LOADERS = {
    "minishlab/potion-retrieval-32M (hybrid, okl.semantic)":
        "from okl import semantic; semantic.load_model(offline=False)",
    "Xenova/ms-marco-MiniLM-L-6-v2 (rerank, okl.rerank)":
        "from okl import rerank; rerank.load_model(offline=False)",
}


def fetched(root: Path) -> tuple[int, int]:
    """Bytes and files under `root`, each file once."""
    seen: set[int] = set()
    total = count = 0
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            st = p.stat()
            if st.st_ino not in seen:
                seen.add(st.st_ino)
                total += st.st_size
                count += 1
    return total, count


def measure(code: str) -> str:
    """The loader run in a fresh process (the hub reads its cache path at import) against an
    empty cache; what it left there."""
    root = Path(tempfile.mkdtemp(prefix="okl-models-"))
    env = {**os.environ, "HF_HOME": str(root / "hf"), "FASTEMBED_CACHE_PATH": str(root / "fastembed"),
           "PYTHONPATH": str(REPO / "src")}
    try:
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                           timeout=900, check=False)
        if r.returncode != 0:
            return f"not measured: {(r.stderr.strip().splitlines() or ['?'])[-1][:160]}"
        size, count = fetched(root)
        return f"{size / 1e6:8.1f} MB ({size / 2**20:.1f} MiB) in {count} files"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    """Measure each model and write the receipt."""
    now = datetime.now(UTC)
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=REPO, check=False).stdout.strip()
    lines = [f"model files · {now:%Y-%m-%dT%H:%MZ} · code {commit} · what each loader fetches into an "
             "empty cache (MB = 10^6 bytes)"]
    lines += [f"  {name:55} {measure(code)}" for name, code in LOADERS.items()]
    out = REPO / "evals" / "results" / f"model-files-{now:%Y%m%d-%H%M}.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines) + f"\nreceipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
