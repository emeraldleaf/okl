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
    """Unset is None, the automatic default; OKL_WARM wins over the config; an empty value falls
    through; an unknown one is refused."""
    assert warm_setting(None, None) is None
    assert warm_setting("", False) is False
    assert warm_setting(None, False) is False
    assert warm_setting(None, True) is True
    assert warm_setting("0", True) is False
    assert warm_setting("on", None) is True
    with pytest.raises(ValueError, match="warm"):
        warm_setting("maybe", None)


def _serving(monkeypatch) -> tuple[Path, threading.Thread]:
    """A stub-model server on a short socket path, answering ping before this returns."""
    path = Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "w.sock"
    monkeypatch.setenv("OKL_WARM_SOCKET", str(path))
    monkeypatch.setattr(warm, "load_model", lambda: _stub)
    server = threading.Thread(target=warm.serve, kwargs={"idle_exit_s": 30}, daemon=True)
    server.start()
    deadline = time.monotonic() + 5
    while warm.ping() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return path, server


def test_a_client_that_vanishes_does_not_end_the_server(monkeypatch):
    """A prompt gives up after TIMEOUT_S and closes its socket; the late answer met a broken pipe
    and ended the server, so the next prompt started another (review on #300)."""
    import socket
    path, server = _serving(monkeypatch)
    for request in (b'{"op": "embed", "kind": "query", "texts": ["a session token"]}\n', b"", b"not json\n"):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(path))
        if request:
            s.sendall(request)
        s.close()   # gone before the answer
    time.sleep(0.2)
    assert warm.ping()["served"] >= 0
    assert server.is_alive()
    warm.stop()
    server.join(timeout=5)


def test_one_server_at_a_time(monkeypatch):
    """While one server holds the lock a second exits at once, and start() spawns nothing: a
    server still loading answers no ping, and every prompt started another (review on #300)."""
    path, server = _serving(monkeypatch)
    assert warm.serve(path, idle_exit_s=1) == 0   # returns at once: the first holds the lock
    assert warm.ping()["served"] == 0
    spawned = []
    monkeypatch.setattr(warm, "installed", lambda: True)
    monkeypatch.setattr(warm, "ping", lambda timeout=warm.TIMEOUT_S: None)   # as while loading
    monkeypatch.setattr(warm.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert warm.start() is None
    assert spawned == []
    monkeypatch.undo()
    monkeypatch.setenv("OKL_WARM_SOCKET", str(path))
    warm.stop()
    server.join(timeout=5)


def test_ping_counts_the_queries_it_answered(monkeypatch):
    """evals/warm_latency.py tells a warm check from a fallback by this count (review on #300)."""
    _path, server = _serving(monkeypatch)
    before = warm.ping()["served"]
    warm.embed(["a session token"], "query")
    assert warm.ping()["served"] == before + 1
    warm.stop()
    server.join(timeout=5)


def test_a_lesson_without_a_vector_answers_to_the_line_for_words(stub):
    """A lesson recorded since the last index has no vector; held to the meaning line on words
    alone, it lost a briefing the model-free decision gave it (review on #300)."""
    s = _store()
    try:
        warm.index(s)
        core.record(s, type="Rule", scope="org", id="fresh", title="rotate webhook signing secrets on schedule")
        task = "rotate the webhook signing secrets"
        assert core.briefed_ids(core.check(s, repo="r", task=task)) == ["fresh"]
        on = core.check(s, repo="r", task=task, warm=True)
        assert on["warm"] is True
        assert "fresh" in core.briefed_ids(on)
    finally:
        s.close()


def test_a_remote_check_says_the_warm_model_did_not_run(monkeypatch):
    """A shared service has no warm model and no field for it; the answer says so rather than
    read as briefed by meaning (review on #300)."""
    from okl.client import Client
    c = Client(config={"repo": "r", "service_url": "http://service.invalid"})
    c.warm = True
    monkeypatch.setattr("okl.client.drift.annotate_briefing", lambda *a, **k: None)
    monkeypatch.setattr(c, "_post", lambda path, body: {"repo": "r", "task": body["task"], "rules": [],
                                                         "match_count": 0, "decision": body["decision"]})
    res = c.check("a task")
    assert res["warm"] is False
    assert "shared service" in res["warm_unavailable"]


def test_a_failed_start_is_said_not_raised(monkeypatch, tmp_path):
    """Starting the server in the background cannot fail the briefing it follows (review on #300)."""
    from okl.client import Client
    monkeypatch.setenv("OKL_WARM_SOCKET", str(Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "none.sock"))
    s = _store()
    warm.set_encoder(_stub)
    warm.index(s)        # vectors present, so the only thing missing is the server
    warm.set_encoder(None)
    c = Client(config={"repo": "r"})
    c.warm = True
    monkeypatch.setattr(c, "_local_store", lambda: s)
    monkeypatch.setattr("okl.client.drift.annotate_briefing", lambda *a, **k: None)
    monkeypatch.setattr(warm, "installed", lambda: True)

    def broken_start(**_k):
        raise OSError("no room to start")
    monkeypatch.setattr(warm, "start", broken_start)
    res = c.check("the session token disappears after a refresh")
    assert "starting it failed: no room to start" in res["warm_unavailable"]


def test_without_flock_start_still_starts_one(monkeypatch):
    """Where flock does not exist the lock is a no-op context, which has no close(); start() raised
    AttributeError into the briefing instead of starting the server (review on #300)."""
    monkeypatch.setenv("OKL_WARM_SOCKET", str(Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "w.sock"))
    monkeypatch.setattr(warm, "fcntl", None)
    monkeypatch.setattr(warm, "installed", lambda: True)
    spawned = []
    monkeypatch.setattr(warm.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert warm.start() is None
    assert len(spawned) == 1


def test_the_person_is_told_when_the_warm_model_did_not_run():
    """The reason was only in the JSON; the line the person sees says it too, and it is the
    check's own word on whether the model ran (review on #300)."""
    from okl.cli.lessons import _person_notes
    notes = _person_notes({"warm_unavailable": "the warm model is not running: `okl warm start`"})
    assert "okl · briefed without the warm model: the warm model is not running: `okl warm start`" in notes
    assert not [n for n in _person_notes({"warm": True}) if "warm" in n]


def test_by_default_the_model_runs_for_an_indexed_store_and_is_silent_otherwise(stub, monkeypatch):
    """The decision recorded in §4z: unset, warm is on for a store `okl warm index` has embedded,
    where the model can load, and says nothing for a store never indexed or a machine without
    the extra; set off, it never runs."""
    monkeypatch.setattr(warm, "installed", lambda: True)
    task = "users get logged out whenever they reload the app"
    s = _store()
    try:
        never = core.check(s, repo="r", task=task, warm=None)
        assert "warm" not in never
        assert "warm_unavailable" not in never
        warm.index(s)
        auto = core.check(s, repo="r", task=task, warm=None)
        assert auto["warm"] is True
        assert core.briefed_ids(auto) == ["tokens"]
        assert core.briefed_ids(core.check(s, repo="r", task=task, warm=False)) == []
        monkeypatch.setattr(warm, "installed", lambda: False)
        elsewhere = core.check(s, repo="r", task=task, warm=None)
        assert "warm_unavailable" not in elsewhere
        assert core.briefed_ids(elsewhere) == []
    finally:
        s.close()
