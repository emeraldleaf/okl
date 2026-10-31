"""evals/bench/run.py: the retrieval bench builds its corpus in a throwaway store of its own."""
import importlib.util
import sqlite3
from pathlib import Path

from okl import store
from okl.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_the_corpus_ignores_the_store_and_service_the_environment_names(tmp_path, monkeypatch):
    """With OKL_DATABASE_URL set, the bench seeded that store and stripped its triggers, and a
    stemmed arm, which switches the tokenizer before the corpus is built, would have rebuilt its
    index on open; with OKL_SERVICE_URL set, it would have sent the seeds to the service (review
    on #308)."""
    real = tmp_path / "real.db"
    Store(f"sqlite:///{real}")
    before = real.read_bytes()
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{real}")
    monkeypatch.setenv("OKL_SERVICE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(store, "FTS_TOKENIZE", "porter unicode61")   # as v2.set_stem(True) does
    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "evals" / "bench" / "run.py")
    bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
    corpus = bench.build_corpus(tmp_path / "corpus")
    assert len(corpus.all_nodes()) > 100
    fts = corpus._impl.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'node_fts'").fetchone()[0]
    assert "porter" in fts
    assert real.read_bytes() == before
    assert sqlite3.connect(real).execute("SELECT count(*) FROM node").fetchone() == (0,)
