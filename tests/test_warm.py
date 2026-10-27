"""The warm model (warm.py, #293, REPORT §4z), with a stub encoder in place of EmbeddingGemma:
what it adds to the briefing, what happens when it does not answer, the index, and the
server's protocol. No model is loaded here."""
import tempfile
import threading
import time
from pathlib import Path

import pytest

from okl import core, warm
from okl.client import warm_setting
from okl.store import Store

# Each concept is a direction; a text points along the concepts whose words it holds.
CONCEPTS = [("logged out", "session", "token", "reload", "refresh"), ("invoice", "billing", "charge")]


def _stub(texts: list[str], _kind: str) -> list[list[float]]:
    rows = []
    for text in texts:
        v = [0.0] * warm.DIM
        for i, words in enumerate(CONCEPTS):
            if any(w in text.lower() for w in words):
                v[i] = 1.0
        if not any(v):
            v[warm.DIM - 1] = 1.0
        norm = sum(x * x for x in v) ** 0.5
        rows.append([x / norm for x in v])
    return rows


@pytest.fixture
def stub():
    """Encode in this process with the stub, and stop after the test."""
    warm.set_encoder(_stub)
    yield
    warm.set_encoder(None)


def _store() -> Store:
    s = Store("sqlite:///:memory:")
    core.record(s, type="Rule", scope="org", id="tokens", title="store access tokens in memory, never in web storage",
                triggers=["the session token disappears after a page refresh"])
    core.record(s, type="Rule", scope="org", id="pages", title="pagination cursor format")
    return s


def test_meaning_briefs_a_lesson_that_shares_no_word_with_the_prompt(stub):
    """A prompt in other words than the lesson's: no full-text candidate, so nothing without the
    model; with it, the model's nearest lesson clears the line by meaning (§4w, §4z)."""
    s = _store()
    try:
        warm.index(s)
        task = "users get logged out whenever they reload the app"
        assert core.briefed_ids(core.check(s, repo="r", task=task)) == []
        on = core.check(s, repo="r", task=task, warm=True)
        assert core.briefed_ids(on) == ["tokens"]
        assert on["warm"] is True
        assert on["rules"][0]["warm_score"] == 1.0
    finally:
        s.close()


def test_without_an_answer_the_briefing_is_the_model_free_one_and_says_why(monkeypatch):
    """No server and no encoder: the same briefing as without the model, the reason in the
    result, and never an exception into the prompt hook."""
    monkeypatch.setenv("OKL_WARM_SOCKET", str(Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "none.sock"))
    s = _store()
    try:
        task = "the session token disappears after a refresh"
        off = core.check(s, repo="r", task=task)
        on = core.check(s, repo="r", task=task, warm=True)
        assert core.briefed_ids(on) == core.briefed_ids(off)
        assert on["warm"] is False
        assert "warm" in on["warm_unavailable"]
    finally:
        s.close()


def test_the_floor_decision_does_not_ask_the_model(stub):
    """The meaning score belongs to the calibrated line; the floor decides on words alone."""
    s = _store()
    try:
        warm.index(s)
        res = core.check(s, repo="r", task="users get logged out whenever they reload", decision="floor", warm=True)
        assert core.briefed_ids(res) == []
        assert "warm_unavailable" not in res
    finally:
        s.close()


def test_the_index_embeds_what_changed_and_drops_what_is_gone(stub):
    """A lesson is embedded once per change of its phrasings, one row per phrasing, and a
    retired lesson's vectors go."""
    s = _store()
    try:
        assert warm.index(s)["embedded"] == 2
        assert warm.index(s)["embedded"] == 0
        core.update(s, "pages", triggers=["the next page repeats the last row"])
        assert warm.index(s)["embedded"] == 1
        core.retire(s, "pages", reason="replaced by keyset pagination")
        assert warm.index(s)["removed"] == 1
        rows = {node_id: blob for node_id, _h, blob in s.embeddings(warm.MODEL_ID)}
        assert len(rows["tokens"]) == 2 * warm.DIM * 4   # title, and one trigger
    finally:
        s.close()


def test_the_server_answers_ping_embed_and_stop(monkeypatch):
    """The protocol end to end over a real socket, the model replaced by the stub."""
    path = Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "w.sock"
    monkeypatch.setenv("OKL_WARM_SOCKET", str(path))
    monkeypatch.setattr(warm, "load_model", lambda: _stub)
    server = threading.Thread(target=warm.serve, kwargs={"idle_exit_s": 30}, daemon=True)
    server.start()
    deadline = time.monotonic() + 5
    while warm.ping() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert warm.ping()["model"] == warm.MODEL_ID
    assert warm.embed(["a session token"], "query") == _stub(["a session token"], "query")
    assert warm.stop() is True
    server.join(timeout=5)
    assert not server.is_alive()
    assert not path.exists()
    assert warm.ping() is None


def test_the_warm_setting_reads_env_over_config():
    """Off unless set; OKL_WARM wins over the config; an unknown value is refused."""
    assert warm_setting(None, None) is False
    assert warm_setting(None, True) is True
    assert warm_setting("0", True) is False
    assert warm_setting("on", None) is True
    with pytest.raises(ValueError, match="warm"):
        warm_setting("maybe", None)
