"""evals/bench/run.py: the retrieval bench builds its corpus in a throwaway store of its own."""
import contextlib
import importlib.util
import sqlite3
import sys
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
    Store(f"sqlite:///{real}").close()
    before = real.read_bytes()
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{real}")
    monkeypatch.setenv("OKL_SERVICE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(store, "FTS_TOKENIZE", "porter unicode61")   # as v2.set_stem(True) does
    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "evals" / "bench" / "run.py")
    bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
    corpus = bench.build_corpus(tmp_path / "corpus")
    try:
        assert len(corpus.all_nodes()) > 100
        fts = corpus._impl.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'node_fts'").fetchone()[0]
        assert "porter" in fts
    finally:
        corpus.close()
    assert real.read_bytes() == before
    with contextlib.closing(sqlite3.connect(real)) as c:
        assert c.execute("SELECT count(*) FROM node").fetchone() == (0,)


def test_pooled_recall_waits_until_every_pair_is_judged(monkeypatch):
    """real_prompts.tally: a pair no judge has seen may apply, so while one is open the pool's
    count of applying lessons is a floor, and recall and F1 over it would read high (review on
    #309). Only the prompts asked about count."""
    monkeypatch.setattr(sys, "path", list(sys.path))     # the script puts evals/bench on the path
    spec = importlib.util.spec_from_file_location("real_prompts", ROOT / "evals" / "bench" / "real_prompts.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    verdict = {("t1", "a"): "APPLIES", ("t1", "b"): None, ("n1", "a"): "DOES_NOT_APPLY"}
    assert rp.pool_open(verdict, ["t1"])
    assert not rp.pool_open(verdict, ["n1"])
    assert not rp.pool_open({("t1", "a"): "APPLIES"}, ["t1"])
