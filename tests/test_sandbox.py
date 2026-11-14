"""evals/sandbox.py: a model call or a check runs without the developer's setup (#446)."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
spec = importlib.util.spec_from_file_location("sandbox", ROOT / "evals" / "sandbox.py")
assert spec and spec.loader
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)


def test_a_child_inherits_no_session_okl_or_git_variable(monkeypatch, tmp_path):
    """The launching session's effort, okl's store and a hook's GIT_DIR all stay behind; what
    signs the CLI in stays."""
    kept = {"CLAUDE_CODE_OAUTH_TOKEN": "fake", "ANTHROPIC_API_KEY": "fake", "HOME": "/home/x",
            "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_FOUNDRY": "1", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD": "1",
            "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION": "us-east-1"}
    gone = {"CLAUDE_EFFORT": "xhigh", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s",
            "OKL_DATABASE_URL": "sqlite:///x", "OKL_DECISION": "tiered", "GIT_DIR": "/elsewhere",
            "GIT_INDEX_FILE": "/elsewhere/index", "MCP_CONNECTION_NONBLOCKING": "1", "ANTHROPIC_MODEL": "m",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "m", "ANTHROPIC_SMALL_FAST_MODEL": "m", "MAX_THINKING_TOKENS": "9",
            "CLAUDE_CODE_USE_POWERSHELL_TOOL": "1", "CLAUDE_CODE_USE_NATIVE_FILE_SEARCH": "1"}
    for k, v in {**gone, **kept}.items():
        monkeypatch.setenv(k, v)
    env = sb.clean_env(tree=tmp_path)
    assert not [k for k in gone if k in env]
    assert env["OKL_WARM"] == "0"   # a check that found no warm model would otherwise start one
    assert {k: env.get(k) for k in kept} == kept
    assert env["PYTHONPATH"] == str(tmp_path / "src") and env["OKL_BRIEFING_LOG"] == "0"
    assert env["PATH"].startswith(str(Path(sys.executable).parent))


def test_effort_is_pinned_before_the_tool_list():
    """--allowedTools takes the rest of the line, so --effort goes right after `claude -p`."""
    argv = ["claude", "-p", "--model", "opus", "--allowedTools", "Read", "Grep"]
    assert sb.with_effort(argv, "medium") == ["claude", "-p", "--effort", "medium", "--model", "opus",
                                               "--allowedTools", "Read", "Grep"]
    for bad in (["claude", "-p", "--effort", "low"], ["python3", "x.py"]):
        with pytest.raises(ValueError):
            sb.with_effort(bad, "medium")
    with pytest.raises(ValueError):
        sb.with_effort(argv, "extreme")


def test_a_model_call_refuses_to_run_inside_the_checkout():
    """§4ba–§4bc's calls ran in the checkout, where CLAUDE.md loads."""
    for inside in (ROOT, ROOT / "evals"):
        with pytest.raises(ValueError, match="inside the checkout"):
            sb.ask(["claude", "-p"], "x", model="opus", effort="low", timeout=1, cwd=inside)


def _envelope(models: list[str], **more: object) -> str:
    return json.dumps({"result": "ok", "modelUsage": {m: {} for m in models}, "total_cost_usd": 0.01,
                       "num_turns": 1, **more})


def test_a_reply_from_another_model_is_an_error(monkeypatch, tmp_path):
    """A usage limit, or an alias that moved, answers from a model the run did not register."""
    seen = {}

    def fake(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout=_envelope(["claude-haiku-5-5"]), stderr="")
    monkeypatch.setattr(sb.subprocess, "run", fake)
    monkeypatch.setenv("CLAUDE_EFFORT", "xhigh")   # set, so its absence below means something
    got = sb.ask(["claude", "-p", "--model", "opus"], "q", model="opus", effort="medium", timeout=5, cwd=tmp_path)
    assert got["error"] == "answered by ['claude-haiku-5-5'], not opus" and got["effort"] == "medium"
    assert seen["cwd"] == tmp_path and "CLAUDE_EFFORT" not in seen["env"] and seen["cmd"][2:4] == ["--effort", "medium"]


def test_a_good_reply_carries_its_models_and_effort(monkeypatch, tmp_path):
    """Background Haiku calls beside the registered model are normal; the row records them all."""
    monkeypatch.setattr(sb.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=_envelope(["claude-haiku-5-5", "claude-opus-5-5"]), stderr=""))
    got = sb.ask(["claude", "-p"], "q", model="opus", effort="low", timeout=5, cwd=tmp_path)
    assert "error" not in got and got["result"] == "ok" and got["models"] == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert (got["cost_usd"], got["turns"], got["effort"]) == (0.01, 1, "low")


def test_a_timeout_an_unreadable_reply_and_an_error_reply_are_errors(monkeypatch, tmp_path):
    """None of them is an answer, and none is silent."""
    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)
    monkeypatch.setattr(sb.subprocess, "run", timeout)
    assert sb.ask(["claude", "-p"], "q", model="opus", effort="low", timeout=5, cwd=tmp_path)["error"] == "timed out after 5s"
    monkeypatch.setattr(sb.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"))
    assert sb.ask(["claude", "-p"], "q", model="opus", effort="low", timeout=5, cwd=tmp_path)["error"] == "boom"
    monkeypatch.setattr(sb.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=_envelope(["claude-opus-5-5"], is_error=True, result="limit reached"), stderr=""))
    assert sb.ask(["claude", "-p"], "q", model="opus", effort="low", timeout=5, cwd=tmp_path)["error"] == "limit reached"


def test_an_empty_room_is_outside_the_checkout_and_empty():
    """Where a call that needs no files runs."""
    with sb.empty_room() as room:
        assert room.is_dir() and not any(room.iterdir()) and not sb.inside_repo(room)
    assert not room.exists()


def test_a_store_copy_carries_what_the_log_holds(tmp_path):
    """okl's store runs in WAL mode; a writer that has not checkpointed holds its rows in the log,
    and copying the file alone dropped them (#446)."""
    import sqlite3
    db = tmp_path / "okl.db"
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE t (x)")
    writer.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
    writer.commit()
    assert (tmp_path / "okl.db-wal").stat().st_size > 0   # the rows are in the log, not the file
    copy = tmp_path / "copy.db"
    sb.copy_sqlite(db, copy)
    with contextlib.closing(sqlite3.connect(copy)) as c:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (50,)
    writer.close()


def test_a_store_copy_survives_a_question_mark_in_its_path(tmp_path):
    """The old URI was built by string: a "?" in a folder name cut the path and created a stray file."""
    import sqlite3
    folder = tmp_path / "we?ird"
    folder.mkdir()
    db = folder / "okl.db"
    with contextlib.closing(sqlite3.connect(db)) as c:
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
    sb.copy_sqlite(db, tmp_path / "copy.db")
    with contextlib.closing(sqlite3.connect(tmp_path / "copy.db")) as c:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (1,)
    assert not (tmp_path / "we").exists()


def test_the_settings_effort_is_read_for_the_receipt(monkeypatch, tmp_path):
    """A call without --restricted reads the user's settings file; the receipt says what it set."""
    import json
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert sb.settings_effort() is None
    (tmp_path / "settings.json").write_text(json.dumps({"effortLevel": "xhigh", "modelSettings": {
        "claude-opus-5": {"effortLevel": "high"}, "claude-sonnet-5-5": {"theme": "x"}}}))
    assert sb.settings_effort() == {"effortLevel": "xhigh", "modelSettings": {"claude-opus-5": "high"}}


def test_a_worktree_of_the_repository_counts_as_inside_it(monkeypatch, tmp_path):
    """A worktree under the temp folder is outside the checkout's path, yet a session there reads this
    repository's git status (review on #451)."""
    repo, wt = tmp_path / "repo", tmp_path / "elsewhere" / "wt"
    ident = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
    subprocess.run(["git", "-C", str(repo), *ident, "commit", "-qm", "c", "--no-verify"], check=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt)], check=True)
    monkeypatch.setattr(sb, "REPO", repo)
    assert sb.inside_repo(wt) and sb.inside_repo(repo)
    assert not sb.inside_repo(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="git status"):
        sb.ask(["claude", "-p"], "x", model="opus", effort="low", timeout=1, cwd=wt)
