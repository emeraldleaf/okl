"""The cross-encoder second stage (REPORT §4t), with a stub model so the suite needs no ML stack."""
from __future__ import annotations

import argparse
import os
import sys

import pytest

from okl import core, rerank
from okl.store import Store


class FakeEncoder:
    """Scores a pair by how many task words the record's subject text contains."""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """One score per document, in fastembed's shape."""
        words = set(query.lower().split())
        return [float(sum(w in words for w in d.lower().replace(".", " ").split())) for d in documents]


@pytest.fixture
def store():
    """A fresh in-memory store, closed after the test."""
    s = Store("sqlite:///:memory:")
    yield s
    s.close()


def test_rerank_reorders_the_pool_and_leaves_the_tail(store, monkeypatch):
    """Only the first `pool` candidates are scored and reordered; the rest keep their order,
    and the scores come back by id."""
    monkeypatch.setattr(rerank, "load_model", lambda *a, **k: FakeEncoder())
    ids = [core.record(store, type="Rule", title=t, scope="org") for t in
           ("pagination caps", "token storage on refresh", "logging hygiene", "refresh token rotation")]
    nodes = [store.get_node(i) for i in ids]
    out, scores = rerank.rerank("refresh the token", nodes, pool=3)
    assert [n.title for n in out] == ["token storage on refresh", "pagination caps", "logging hygiene", "refresh token rotation"]
    assert set(scores) == set(ids[:3]) and scores[ids[1]] == 2.0
    assert rerank.rerank("anything", [], pool=3) == ([], {})


def test_rerank_says_why_when_the_model_is_missing(store, monkeypatch):
    """Without the extra or the cached model the error names the remedy; nothing is reordered."""
    def missing(*a, **k):
        raise rerank.RerankUnavailableError("the rerank extra is not installed")
    monkeypatch.setattr(rerank, "load_model", missing)
    n = store.get_node(core.record(store, type="Rule", title="t", scope="org"))
    with pytest.raises(rerank.RerankUnavailableError, match="extra"):
        rerank.rerank("task", [n])


def test_pair_text_is_the_subject_not_the_cause(store):
    """The cross-encoder reads title, symptom and aliases, never the cause paragraph."""
    n = store.get_node(core.record(store, type="Rule", title="token storage", scope="org",
                                   symptom="a token in web storage", aliases="logged out on refresh",
                                   body="a long cause paragraph that the reranker should not read"))
    assert rerank.pair_text(n) == "token storage. a token in web storage. logged out on refresh"


def test_check_reranks_the_candidates_and_records_the_scores(store, monkeypatch):
    """With the second stage on, the candidate the cross-encoder prefers moves ahead of the one
    the first stage ranked higher, each briefed record carries its score, and the result says
    the stage ran; without the extra the first-stage order stands and the result says why."""
    core.record(store, type="Rule", title="refresh tokens rotate", scope="org",
                symptom="a refresh token reused after rotation")
    core.record(store, type="Rule", title="token storage", scope="org",
                symptom="a refresh token kept in web storage")
    task = "rotate the refresh token"
    plain = core.check(store, repo="r", task=task)
    first, second = [r["id"] for r in plain["rules"]]
    assert "rerank" not in plain
    preferred = store.get_node(second).title

    class Prefers:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            return [1.0 if preferred in d else -1.0 for d in documents]

    monkeypatch.setattr(rerank, "load_model", lambda *a, **k: Prefers())
    res = core.check(store, repo="r", task=task, rerank=True)
    assert [r["id"] for r in res["rules"]] == [second, first] and res["rerank"] is True
    assert res["rules"][0]["rerank_score"] == 1.0 and res["rules"][1]["rerank_score"] == -1.0

    def missing(*a, **k):
        raise rerank.RerankUnavailableError("the rerank extra is not installed")
    monkeypatch.setattr(rerank, "load_model", missing)
    res = core.check(store, repo="r", task=task, rerank=True)
    assert [r["id"] for r in res["rules"]] == [first, second] and res["rerank"] is False
    assert "extra" in res["rerank_unavailable"]


def test_rerank_setting_reads_the_environment_over_the_config():
    """OKL_RERANK wins over the config key; off and empty disable; on and 1 enable."""
    from okl.client import rerank_setting
    assert rerank_setting(None, None) is False and rerank_setting(None, True) is True
    assert rerank_setting("off", True) is False and rerank_setting("1", None) is True
    with pytest.raises(ValueError, match="rerank"):
        rerank_setting("maybe", None)


def test_check_reports_the_reranker_off_when_the_task_has_no_subject_words(store, monkeypatch):
    """A task with nothing to search on runs no stage; the result must not say the second
    stage ran (review on #271)."""
    monkeypatch.setattr(rerank, "load_model", lambda *a, **k: FakeEncoder())
    res = core.check(store, repo="r", task="the of and", rerank=True)
    assert res["rerank"] is False and "no subject words" in res["rerank_unavailable"]


def test_embed_caches_the_reranker_without_the_embedding_extra(tmp_path, monkeypatch, capsys):
    """An install with only the rerank extra still needs `okl embed` to fetch its model: the
    embedding step's failure is reported and the command goes on to the reranker, exiting 2
    for the step that failed (review on #271)."""
    from okl import semantic
    from okl.cli.embed import cmd_embed

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text('{"repo": "r", "database_url": "sqlite:///:memory:"}')
    monkeypatch.delenv("OKL_DATABASE_URL", raising=False)
    monkeypatch.delenv("OKL_SERVICE_URL", raising=False)

    def no_embedder(store):
        raise semantic.SemanticUnavailableError("the hybrid extra is not installed")
    monkeypatch.setattr(semantic, "build_index", no_embedder)
    loaded = []
    monkeypatch.setattr(rerank, "load_model", lambda *a, **k: loaded.append(k) or FakeEncoder())
    rc = cmd_embed(argparse.Namespace())
    out = capsys.readouterr()
    assert rc == 2 and "NOT EMBEDDED" in out.err
    assert loaded == [{"offline": False}] and "reranker" in out.out


def test_load_model_serialises_concurrent_first_loads(monkeypatch):
    """Two threads loading at once must not race on the process-wide offline flag: the second
    waits for the first and finds the cache (review on #271)."""
    import threading
    import types

    calls = []

    class Encoder:
        def __init__(self, model_name):
            calls.append(model_name)
            threading.Event().wait(0.05)

    fake = types.ModuleType("fastembed.rerank.cross_encoder"); fake.TextCrossEncoder = Encoder
    monkeypatch.setitem(sys.modules, "fastembed", types.ModuleType("fastembed"))
    monkeypatch.setitem(sys.modules, "fastembed.rerank", types.ModuleType("fastembed.rerank"))
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", fake)
    monkeypatch.setattr(rerank, "_LOADED", {})
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    threads = [threading.Thread(target=rerank.load_model, kwargs={"model_id": "m"}) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert calls == ["m"] and "HF_HUB_OFFLINE" not in os.environ
