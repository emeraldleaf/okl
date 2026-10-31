"""Stemming (REPORT §4ac, §4ad): a word matches another form of itself in the full-text index,
in the calibrated line's shared words and in the floor's, one tokenizer deciding all three. A
measured setting, off by default (§4ad), so every test here turns it on."""
from __future__ import annotations

import contextlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from okl import core, decide
from okl import store as okl_store
from okl.store import Store


@pytest.fixture(autouse=True)
def stemming(monkeypatch):
    """The setting §4ad measured: the porter index and its stemmed line."""
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "porter unicode61")
    monkeypatch.setattr(decide, "CALIBRATED_LINE", 3.0014486)


@pytest.fixture
def store():
    """A fresh in-memory store, closed after the test."""
    s = Store("sqlite:///:memory:")
    yield s
    s.close()


def test_an_index_built_unstemmed_is_rebuilt_stemmed_once_when_opened(tmp_path, monkeypatch):
    """A store from before stemming finds nothing by another form of a word; opening it rebuilds
    its index from the node table, and the next open finds nothing left to rebuild."""
    db = tmp_path / "okl.db"
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "unicode61")
    s = Store(f"sqlite:///{db}")
    nid = core.record(s, type="Rule", title="rotate the signing secret", scope="org")
    assert not s.search("rotating", limit=5)
    s.close()
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "porter unicode61")
    s = Store(f"sqlite:///{db}")
    try:
        assert [n.id for n in s.search("rotating", limit=5)] == [nid]
        assert not s._impl._fts_stale()
    finally:
        s.close()
    with contextlib.closing(sqlite3.connect(db)) as c:
        assert "porter" in c.execute("SELECT sql FROM sqlite_master WHERE name='node_fts'").fetchone()[0]


def test_a_rebuild_that_fails_leaves_the_index_it_found(tmp_path, monkeypatch):
    """A rebuild that fails after dropping the index is rolled back. Committed, the next open
    would create an empty index that looks current, and search would miss every lesson (review on
    #309)."""
    db = tmp_path / "okl.db"
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "unicode61")
    s = Store(f"sqlite:///{db}")
    nid = core.record(s, type="Rule", title="rotate the signing secret", scope="org")
    s.close()
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "no_such_tokenizer")
    Store(f"sqlite:///{db}").close()   # the CREATE after the DROP fails
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "unicode61")
    s = Store(f"sqlite:///{db}")
    try:
        assert [n.id for n in s.search("signing", limit=5)] == [nid]
    finally:
        s.close()


def test_the_line_and_the_floor_count_another_form_of_a_word(store):
    """"rotate the webhook signing secrets" shares four words with a lesson about "rotating the
    webhook signing secret": the line briefs it, the floor keeps it, and both name the words as
    the prompt has them, not as stems."""
    nid = core.record(store, type="Rule", title="rotating the webhook signing secret", scope="org")
    task = "rotate the webhook signing secrets"
    for decision in ("calibrated", "floor"):
        res = core.check(store, repo="r", task=task, decision=decision)
        assert core.briefed_ids(res) == [nid], decision
        assert res["rules"][0]["matched_terms"] == ["rotate", "webhook", "signing", "secrets"], decision


def test_the_floor_counts_two_forms_of_one_word_once(store):
    """"migrate" and "migrations" are one word shared with a lesson that says "migration" only in
    its body, as the line counts them, so the two-word floor does not keep it on that alone
    (review on #309)."""
    core.record(store, type="Rule", title="keep schema changes reversible",
                body="a migration that never finished", scope="org")
    res = core.check(store, repo="r", task="migrate the migrations before deploy", decision="floor")
    assert not core.briefed_ids(res)


def test_a_stem_counts_once_however_many_words_share_it(store):
    """Two forms of one word are one shared word to the line, as on the bench that set it (§4ac)."""
    core.record(store, type="Rule", title="migration order", scope="org")
    nodes = store.all_nodes()
    sc, shared = decide.score(["migrate", "migrations", "order"], nodes[0], decide.Rarity(nodes))
    assert shared == ["migrate", "order"]
    assert int(sc) == 2


def test_a_word_the_tokenizer_splits_is_stemmed_on_its_own_row(monkeypatch):
    """stems() reads one row of every word back in order; a word the tokenizer split in two would
    shift every stem after it, so then each word is stemmed alone."""
    monkeypatch.setattr(decide, "_STEMS", {})
    got = decide.stems(["rotating", "half-baked", "secrets"])
    assert (got["rotating"], got["half-baked"], got["secrets"]) == ("rotat", "half", "secret")


def test_without_fts5_a_word_is_its_own_stem(monkeypatch):
    """A Python whose SQLite lacks FTS5 searches by LIKE and matches words as typed."""
    class NoFts:
        def execute(self, *_a):
            raise sqlite3.OperationalError("no such module: fts5")

        def close(self):
            pass
    monkeypatch.setattr(decide.sqlite3, "connect", lambda *_a: NoFts())
    monkeypatch.setattr(decide, "_STEMS", {})
    assert decide.stems(["rotating"]) == {"rotating": "rotating"}


def test_the_latency_runs_never_reach_a_service(tmp_path, monkeypatch):
    """A service named in the environment or the checkout's config sends both timed arms to it,
    whatever OKL_DATABASE_URL says: the variable is dropped, and a config naming one refuses the
    run (review on #309)."""
    script = Path(__file__).resolve().parents[1] / "evals" / "stem_latency.py"
    spec = importlib.util.spec_from_file_location("stem_latency", script)
    lat = importlib.util.module_from_spec(spec); spec.loader.exec_module(lat)
    monkeypatch.setenv("OKL_SERVICE_URL", "http://127.0.0.1:9")
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text('{"repo": "r"}')
    assert "OKL_SERVICE_URL" not in lat.child_env(tmp_path)
    (tmp_path / ".okl" / "config.json").write_text('{"repo": "r", "service_url": "http://127.0.0.1:9"}')
    with pytest.raises(SystemExit, match="names a service"):
        lat.child_env(tmp_path)
