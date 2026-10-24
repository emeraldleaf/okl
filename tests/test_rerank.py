"""The cross-encoder second stage (REPORT §4t), with a stub model so the suite needs no ML stack."""
from __future__ import annotations

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
