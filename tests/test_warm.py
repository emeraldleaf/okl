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
    assert warm.serve(path, idle_exit_s=1) == 0   # gives up after a second: the first holds the lock
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


def test_by_default_the_model_runs_for_a_local_indexed_store_and_is_silent_otherwise(stub, monkeypatch):
    """The decision recorded in §4z: unset, warm is on for a local store `okl warm index` has
    embedded, where the model can load, and says nothing for a store never indexed, a shared
    store, or one stopped with `okl warm stop`; set off, it never runs (review on #300)."""
    from okl.store import Store as StoreClass
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
        with monkeypatch.context() as m:   # a shared database: one person's index is not everyone's opt-in
            m.setattr(StoreClass, "local", property(lambda self: False))
            shared = core.check(s, repo="r", task=task, warm=None)
            assert "warm" not in shared and core.briefed_ids(shared) == []
        warm.stop()                        # no server answers; the record is what keeps it off
        stopped = core.check(s, repo="r", task=task, warm=None)
        assert "warm" not in stopped and "warm_unavailable" not in stopped
    finally:
        s.close()


def test_an_indexed_store_that_lost_the_extra_says_so(stub, monkeypatch):
    """An upgrade that reinstalls without the warm extra turned the model off with no word; the
    store's own vectors say the person opted in (review on #300)."""
    s = _store()
    try:
        warm.index(s)
        monkeypatch.setattr(warm, "installed", lambda: False)
        res = core.check(s, repo="r", task="users get logged out whenever they reload the app", warm=None)
        assert "extra is not installed" in res["warm_unavailable"]
        assert res["warm_reason"] == "unavailable" and res["warm"] is False
    finally:
        s.close()


def _client_on(monkeypatch, s, warm_setting=None):
    """A local Client over `s`, with the warm setting given and drift marks off."""
    from okl.client import Client
    c = Client(config={"repo": "r"})
    c.warm = warm_setting
    monkeypatch.setattr(c, "_local_store", lambda: s)
    monkeypatch.setattr("okl.client.drift.annotate_briefing", lambda *a, **k: None)
    return c


def test_a_prompt_that_finds_no_server_starts_one_and_not_one_per_prompt(monkeypatch):
    """The default starts the server for the next prompt and says so; a server that did not come
    up is not started again on every prompt, and the line names its log (review on #300)."""
    s = _store()
    warm.set_encoder(_stub)
    warm.index(s)
    warm.set_encoder(None)
    monkeypatch.setattr(warm, "installed", lambda: True)
    spawned = []
    monkeypatch.setattr(warm.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    c = _client_on(monkeypatch, s)
    first = c.check("the session token disappears after a refresh")
    assert first["warm_reason"] == "not_running"
    assert "starting now for the next prompt" in first["warm_unavailable"]
    assert len(spawned) == 1
    soon = c.check("the session token disappears after a refresh")      # still coming up
    assert "still loading" in soon["warm_unavailable"]
    import os
    old = time.time() - warm.STARTING_S - 1                            # and then it never came up
    os.utime(warm._started_path(), (old, old))
    second = c.check("the session token disappears after a refresh")
    assert "did not come up after its last start" in second["warm_unavailable"]
    assert str(warm.log_path()) in second["warm_unavailable"]
    assert len(spawned) == 1


def test_okl_warm_stop_is_not_undone_by_the_next_prompt(monkeypatch):
    """`okl warm stop` was undone at once: the next prompt found no server and started one
    (review on #300). Asked for explicitly, the stopped model says how to resume it."""
    s = _store()
    warm.set_encoder(_stub)
    warm.index(s)
    warm.set_encoder(None)
    monkeypatch.setattr(warm, "installed", lambda: True)
    spawned = []
    monkeypatch.setattr(warm.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert warm.stop() is False                     # none was running; it stays off anyway
    auto = _client_on(monkeypatch, s).check("the session token disappears after a refresh")
    assert "warm_unavailable" not in auto
    asked = _client_on(monkeypatch, s, True).check("the session token disappears after a refresh")
    assert "stopped with `okl warm stop`" in asked["warm_unavailable"]
    assert spawned == []
    warm.start()                                   # the default's start for a prompt keeps the stop
    assert warm.stopped() and len(spawned) == 1
    warm.resume()                                  # the person's own start, index or serve undoes it
    assert not warm.stopped()


def test_the_server_is_started_detached_from_the_prompt_hook(monkeypatch):
    """The hook reads okl's output through $(...), which waits for every holder of the pipe: a
    server that inherited it would hold the prompt to Claude Code's 30 s limit (review on #300)."""
    import subprocess
    monkeypatch.setattr(warm, "installed", lambda: True)
    calls = []
    monkeypatch.setattr(warm.subprocess, "Popen", lambda *a, **k: calls.append(k))
    warm.start()
    (k,) = calls
    assert k["stdin"] is subprocess.DEVNULL and k["stderr"] is subprocess.STDOUT
    assert k["stdout"] not in (None, subprocess.PIPE) and k["stdout"].name == str(warm.log_path())
    assert k["start_new_session"] is True and k["close_fds"] is True


def test_the_lines_are_the_receipts_and_just_above_them():
    """Both briefing lines were copied by hand from a receipt, and a comment's copy slipped a
    digit (review on #300): each constant is the receipt's line at alpha 0.05, just above it."""
    import re

    from okl import decide
    text = (Path(__file__).resolve().parents[1] / "evals" / "results"
            / "bench-20261027-sel-dense-embeddinggemma-int8-words.txt").read_text()
    exact = next(ln for ln in text.splitlines() if ln.startswith("exact lines:"))
    for weight, line in ((8, warm.LINE), (0, decide.CALIBRATED_LINE)):
        m = re.search(rf"\bW {weight}: ([0-9.]+)", exact)
        assert m, f"no W {weight} line in the receipt"
        assert float(m.group(1)) < line <= float(m.group(1)) + 1e-6


def test_meaning_only_neighbours_are_not_counted_as_weak_matches(stub):
    """With the model on, the calibrated decision scored the model's own neighbours too, and the
    briefing said they shared too little of the task's subject (review on #300)."""
    s = _store()
    try:
        warm.index(s)
        task = "users get logged out whenever they reload the app"
        words = core.check(s, repo="r", task=task, decision="calibrated")
        on = core.check(s, repo="r", task=task, decision="calibrated", warm=True)
        assert core.briefed_ids(on) == ["tokens"]
        assert on["weak_matches"] == words["weak_matches"] == 0
    finally:
        s.close()


def _latency():
    """evals/warm_latency.py as a module (a script, not part of the package)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "warm_latency", Path(__file__).resolve().parents[1] / "evals" / "warm_latency.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_latency_receipt_times_the_decision_that_asks_the_model():
    """The floor never asks the model, so OKL_DECISION=floor in the caller's environment would
    time no model at all (review on #300)."""
    cmd = _latency().check_cmd("on", "rotate the secrets")
    assert cmd[cmd.index("--decision") + 1] == "tiered"


def test_only_a_prompt_that_asked_the_model_counts_toward_what_it_added():
    """A prompt that names no subject asks nothing, so its difference is not the model's
    (review on #300)."""
    times = {"on": [300.0, 130.0, 260.0], "off": [100.0, 120.0, 110.0]}
    assert _latency().model_diffs(times, [True, False, True]) == [150.0, 200.0]


def test_a_stop_reaches_a_server_that_was_loading_or_busy(monkeypatch):
    """A stop sent while the server loaded found no socket, and one that timed out while it was
    busy was never read: 1.6 GB stayed up for hours (review on #300). The record it leaves is."""
    path = Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "w.sock"
    monkeypatch.setenv("OKL_WARM_SOCKET", str(path))
    monkeypatch.setattr(warm, "load_model", lambda: _stub)
    assert warm.stop() is False                    # nothing answers yet: it is still loading
    assert warm.serve(path, idle_exit_s=30) == 0   # and exits once loaded, never serving
    assert not path.exists()
    warm.resume()
    path, server = _serving(monkeypatch)
    warm._stopped_path().touch()                   # a stop whose request was never answered
    warm.ping()                                    # the next connection wakes the loop
    server.join(timeout=5)
    assert not server.is_alive()


def test_a_start_still_coming_up_reads_as_loading_not_failed(monkeypatch):
    """The new process has not taken the lock in its first seconds; a prompt then was told the
    start had failed (review on #300)."""
    import os
    monkeypatch.setattr(warm, "installed", lambda: True)
    spawned = []
    monkeypatch.setattr(warm.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    warm._started_path().parent.mkdir(parents=True, exist_ok=True)
    warm._started_path().touch()
    assert warm.revive() == "loading" and spawned == []
    old = time.time() - warm.STARTING_S - 1
    os.utime(warm._started_path(), (old, old))
    assert warm.revive() == "failed" and spawned == []
    old = time.time() - warm.RESTART_AFTER_S - 1
    os.utime(warm._started_path(), (old, old))
    assert warm.revive() == "started" and len(spawned) == 1


def test_a_server_that_cannot_take_the_lock_says_so(monkeypatch, capsys):
    """A start's probe holds the lock for an instant, and a server meeting it exited with no
    word, so the log a failed start points at was empty (review on #300)."""
    path = Path(tempfile.mkdtemp(prefix="okl", dir="/tmp")) / "w.sock"
    held = warm._take_lock(path)
    try:
        assert warm.serve(path, idle_exit_s=1) == 0
    finally:
        held.close()
    assert "another server holds the lock" in capsys.readouterr().err


def test_a_platform_without_unix_sockets_is_unavailable_not_an_error(monkeypatch):
    """Without AF_UNIX, _ask raised AttributeError past every caller (review on #300)."""
    monkeypatch.delattr(warm.socket, "AF_UNIX")
    assert warm.ping() is None
    with pytest.raises(warm.WarmUnavailableError, match="Unix sockets") as err:
        warm.embed(["a"], "query")
    assert err.value.reason == "unavailable"     # not "not_running": nothing to start


def test_only_a_held_lock_reads_as_another_server(monkeypatch, tmp_path):
    """Every OSError from flock read as another server, so ENOLCK made start() skip spawning and
    revive() report "loading" for ever (review on #300)."""
    import errno
    from types import SimpleNamespace

    def flock_raising(exc):
        def flock(*_a):
            raise exc
        return SimpleNamespace(flock=flock, LOCK_EX=2, LOCK_NB=4)
    monkeypatch.setattr(warm, "fcntl", flock_raising(BlockingIOError(errno.EWOULDBLOCK, "held")))
    assert warm._take_lock(tmp_path / "w.sock") is None
    monkeypatch.setattr(warm, "fcntl", flock_raising(OSError(errno.ENOLCK, "No locks available")))
    with pytest.raises(warm.WarmUnavailableError, match="lock could not be taken"):
        warm._take_lock(tmp_path / "w.sock")


def test_the_model_revision_is_the_cached_snapshot(monkeypatch, tmp_path):
    """The real-prompt bench keys its document vectors on it, so new model files cannot meet
    vectors the old ones made (review on #300)."""
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    assert warm.model_revision() == ""
    (tmp_path / "models--onnx-community--embeddinggemma-300m-ONNX" / "onnx_snapshots" / "abc123").mkdir(parents=True)
    assert warm.model_revision() == "abc123"


def test_a_harness_prompt_does_not_count_as_asking_the_model():
    """core.check gates a harness-wrapped prompt before the model, but the latency receipt counted
    its model-free timing as the model's (review on #300)."""
    lat = _latency()
    assert lat.asks_model("rotate the webhook signing secrets")
    assert not lat.asks_model("<task-notification>rotate the webhook signing secrets</task-notification>")
    assert not lat.asks_model("ok")
