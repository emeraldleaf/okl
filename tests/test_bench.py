"""evals/bench/run.py: the retrieval bench builds its corpus in a throwaway store of its own."""
import importlib.util
from pathlib import Path

from okl.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_the_corpus_ignores_the_store_and_service_the_environment_names(tmp_path, monkeypatch):
    """With OKL_DATABASE_URL set, the bench seeded that store, stripped its triggers and could
    rebuild its index with porter_index; with OKL_SERVICE_URL set, it would have sent the seeds
    to the service (review on #308)."""
    real = tmp_path / "real.db"
    Store(f"sqlite:///{real}")
    before = real.read_bytes()
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{real}")
    monkeypatch.setenv("OKL_SERVICE_URL", "http://127.0.0.1:9")
    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "evals" / "bench" / "run.py")
    bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
    corpus = bench.build_corpus(tmp_path / "corpus")
    bench.porter_index(corpus)
    assert len(corpus.all_nodes()) > 100
    assert Store(f"sqlite:///{real}").all_nodes() == [] and real.read_bytes() == before
