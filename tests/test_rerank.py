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
        def __init__(self, model_name, cache_dir=None):
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


def test_both_loaders_share_one_lock_and_one_offline_switch(monkeypatch):
    """An offline reranker load and an online embedder load at the same time: each sees the
    switch it asked for throughout its load, and the switch is as it was afterwards. Two
    locks would let one loader restore the other's value (review on #271)."""
    import threading
    import types

    from okl import semantic

    seen = {}

    class Encoder:
        def __init__(self, model_name, cache_dir=None):
            seen["rerank-start"] = os.environ.get("HF_HUB_OFFLINE")
            threading.Event().wait(0.05)
            seen["rerank-end"] = os.environ.get("HF_HUB_OFFLINE")

    class Static:
        @staticmethod
        def from_pretrained(model_id):
            seen["embed-start"] = os.environ.get("HF_HUB_OFFLINE")
            threading.Event().wait(0.05)
            seen["embed-end"] = os.environ.get("HF_HUB_OFFLINE")
            return object()

    fe = types.ModuleType("fastembed.rerank.cross_encoder"); fe.TextCrossEncoder = Encoder
    m2v = types.ModuleType("model2vec"); m2v.StaticModel = Static
    for name, mod in (("fastembed", types.ModuleType("fastembed")), ("fastembed.rerank", types.ModuleType("fastembed.rerank")),
                      ("fastembed.rerank.cross_encoder", fe), ("model2vec", m2v)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(rerank, "_LOADED", {})
    monkeypatch.setattr(semantic, "_LOADED", {})
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    threads = [threading.Thread(target=rerank.load_model, kwargs={"model_id": "r", "offline": True}),
               threading.Thread(target=semantic.load_model, kwargs={"model_id": "s", "offline": False})]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert seen["rerank-start"] == seen["rerank-end"] == "1"
    assert seen["embed-start"] is None and seen["embed-end"] is None
    assert "HF_HUB_OFFLINE" not in os.environ


def test_the_offline_switch_reaches_huggingface_hubs_own_constant(monkeypatch):
    """huggingface_hub reads HF_HUB_OFFLINE once, at import. After an online first load had
    imported it, a check-time load set the variable and still went to the network (twelve
    attempts, a stalled suite on a slow network). The switch sets the module's constant too,
    and afterwards leaves it as a fresh import would read the restored variable."""
    import types

    from okl import hub

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    constants = types.SimpleNamespace(HF_HUB_OFFLINE=False)    # imported by an online load
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    with hub.loading(offline=True):
        assert constants.HF_HUB_OFFLINE is True
    assert constants.HF_HUB_OFFLINE is False and "HF_HUB_OFFLINE" not in os.environ

    # First imported inside an offline block, it froze True; online loads afterwards must not stay offline.
    monkeypatch.delitem(sys.modules, "huggingface_hub.constants")
    with hub.loading(offline=True):
        late = types.SimpleNamespace(HF_HUB_OFFLINE=True)
        monkeypatch.setitem(sys.modules, "huggingface_hub.constants", late)
    assert late.HF_HUB_OFFLINE is False
    with hub.loading(offline=False):
        assert late.HF_HUB_OFFLINE is False

    # The user's own offline setting, in either variable, holds through an online load and after it.
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "yes")
    with hub.loading(offline=False):
        assert late.HF_HUB_OFFLINE is True
    assert late.HF_HUB_OFFLINE is True


def test_the_reranker_is_cached_under_the_cache_home_not_the_temp_dir(monkeypatch, tmp_path):
    """fastembed's default cache is the system temp directory, which macOS prunes; okl passes
    an explicit directory under the cache home, and honours fastembed's own override."""
    import types

    from okl import hub

    seen = {}

    class Encoder:
        def __init__(self, model_name, cache_dir=None):
            seen["cache_dir"] = cache_dir

    fe = types.ModuleType("fastembed.rerank.cross_encoder"); fe.TextCrossEncoder = Encoder
    for name, mod in (("fastembed", types.ModuleType("fastembed")), ("fastembed.rerank", types.ModuleType("fastembed.rerank")),
                      ("fastembed.rerank.cross_encoder", fe)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(rerank, "_LOADED", {})
    rerank.load_model("m")
    assert seen["cache_dir"] == str(tmp_path / "xdg" / "okl" / "models")   # pytest's tmp is itself under $TMPDIR

    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert hub.model_cache_dir() == tmp_path / "home" / ".cache" / "okl" / "models"

    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "theirs"))
    monkeypatch.setattr(rerank, "_LOADED", {})
    rerank.load_model("m")
    assert seen["cache_dir"] == str(tmp_path / "theirs")
