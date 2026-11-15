"""The review log's store, command and report (#464).

`okl recap --transcript <path> --log-review` writes one row per session; `okl recap --reviews`
reads the rows back. The parser is tested in test_review_log.py, the Stop hook's side in
test_review_log_hook.py. Transcripts are synthetic (tests/review_transcripts.py).
"""
import json
import signal
import sqlite3
import time
from pathlib import Path

import pytest
from review_transcripts import (
    call,
    repo_root,
    result,
    say,
    start_review,
    turn,
    two_agents,
    user,
    write,
)

from okl import recap
from okl import store as store_mod
from okl.cli import lessons, main
from okl.client import Client
from okl.store import Store

# --- the store ---------------------------------------------------------------------------------


def test_a_session_logged_again_replaces_its_row(tmp_path):
    """One row per (session, repo): the transcript grew since the last stop, so the last reading wins."""
    s = Store(f"sqlite:///{tmp_path / 'okl.db'}")
    check = {"agent": "a", "model": "opus", "lessons": ["l1"], "edited": True, "edited_files": ["x.py"],
             "edited_outside": 0, "tests": [], "tokens": 5, "cache_read_tokens": 50, "read": True}
    s.log_review("s1", "r", asked=True, ran=False)
    s.log_review("s1", "r", asked=True, ran=True, files_changed=3, lessons_listed=9, tokens=100,
                 cache_read_tokens=2_000_000, duration_s=40, failed_launches=2, checks=[check])
    s.log_review("s1", "other", asked=False, ran=True)
    s.log_review("s2", "r", asked=True, ran=False)

    mine = s.reviews("r")

    assert [(x.session_id, x.asked, x.ran) for x in mine] == [("s1", True, True), ("s2", True, False)]
    first = mine[0]
    assert (first.files_changed, first.lessons_listed, first.tokens, first.duration_s) == (3, 9, 100, 40)
    assert (first.cache_read_tokens, first.failed_launches) == (2_000_000, 2)
    assert first.checks == (check,) and isinstance(first.asked, bool)
    assert (mine[1].files_changed, mine[1].tokens, mine[1].checks) == (None, None, ())
    assert (mine[1].cache_read_tokens, mine[1].failed_launches) == (None, 0)
    assert len(s.reviews()) == 3 and [x.repo for x in s.reviews("other")] == ["other"]


def test_a_store_from_before_the_log_gains_its_table_when_opened(tmp_path):
    """An older okl never made `review_run`: opening the store makes it, and keeps what was in it."""
    path = tmp_path / "okl.db"
    s = Store(f"sqlite:///{path}")
    s.add_node(store_mod.Node(id="l1", type="Rule", scope="org", title="a lesson"))
    s.close()
    db = sqlite3.connect(path)
    db.execute("DROP TABLE review_run"); db.commit(); db.close()

    reopened = Store(f"sqlite:///{path}")
    reopened.log_review("s", "r", asked=True, ran=False)

    assert [x.session_id for x in reopened.reviews()] == ["s"]
    assert reopened.get_node("l1") is not None


def test_rows_logged_in_the_same_millisecond_come_back_in_one_order(tmp_path, monkeypatch):
    """A tie on the time breaks on repo then session, which both backends hold: a replaced row keeps its
    id on Postgres and gets a new rowid on SQLite, so neither can say which came first."""
    monkeypatch.setattr(store_mod, "_now_ms", lambda: 1_000)
    s = Store(f"sqlite:///{tmp_path / 'okl.db'}")
    for session, repo in (("s1", "r"), ("s2", "r"), ("s0", "other")):
        s.log_review(session, repo, asked=True, ran=False)
    s.log_review("s1", "r", asked=True, ran=True)      # replaced: it must not move to the end

    assert [(x.repo, x.session_id) for x in s.reviews()] == [("other", "s0"), ("r", "s1"), ("r", "s2")]
    assert [x.session_id for x in s.reviews("r")] == ["s1", "s2"]


# --- the command -----------------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repository with a local store and two lessons."""
    for var in ("OKL_REVIEW_LOG", "OKL_REVIEW_AFTER_WRITING", "OKL_SERVICE_URL", "OKL_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"; (r / ".okl").mkdir(parents=True)
    (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.chdir(r)
    c = Client()
    c.record(id="les-a", type="Rule", title="the first lesson", scope="org")
    c.record(id="les-b", type="Rule", title="the second lesson", scope="org")
    return r


def _rows(repo: Path):
    return Client()._local_store().reviews("r")


def _log(tmp_path, repo, *extra):
    """`okl recap --log-review` on the two-agent session whose edits are inside `repo`."""
    t = two_agents(tmp_path, repo)
    return main(["recap", "--transcript", str(t), "--log-review", *extra])


def test_log_review_writes_the_row_and_exits_0(repo, tmp_path, capsys):
    """The command reads the transcript, writes the row with paths relative to the repository, and a
    later stop of the same session replaces it rather than adding a second."""
    t = two_agents(tmp_path, repo)

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0

    got = capsys.readouterr()
    assert "logged session sess-1" in got.err and got.out == ""
    (row,) = _rows(repo)
    assert (row.session_id, row.asked, row.ran, row.files_changed, row.lessons_listed) == ("sess-1", True, True, 4, 12)
    assert [c["lessons"] for c in row.checks] == [["les-a"], ["les-b"]]
    assert row.checks[0]["edited_files"] == ["src/x.py"]       # relative to the repository okl runs in
    assert row.checks[0]["model"] == "claude-opus-5-5"
    # the work and the cache reads apart, in the row and in each check
    assert (row.tokens, row.cache_read_tokens) == (111, 61)
    assert [(c["tokens"], c["cache_read_tokens"]) for c in row.checks] == [(12, 4), (12, 4)]
    # a later stop of the same session replaces the row
    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0
    assert len(_rows(repo)) == 1


def test_log_review_exits_0_and_writes_nothing_when_there_was_no_review(repo, tmp_path, capsys):
    """A session with no review, and a transcript that cannot be read, are both exit 0 and no row."""
    quiet = write(tmp_path, [user(0, "x"), turn(5, "m1", say("ok"))], session="quiet")

    assert main(["recap", "--transcript", str(quiet), "--log-review"]) == 0
    assert "nothing logged" in capsys.readouterr().err
    assert main(["recap", "--transcript", str(tmp_path / "gone.jsonl"), "--log-review"]) == 0
    assert "cannot read" in capsys.readouterr().err
    assert _rows(repo) == []


def test_log_review_exits_2_when_the_store_cannot_be_written(repo, tmp_path, monkeypatch, capsys):
    """A store that refuses the write is the failure the caller must hear of."""
    t = two_agents(tmp_path, repo)

    def refuse(self, run):
        raise sqlite3.OperationalError("attempt to write a readonly database")
    monkeypatch.setattr(store_mod._SQLiteBackend, "log_review", refuse)

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 2
    err = capsys.readouterr().err
    assert "review log cannot be used" in err and "readonly" in err


def test_log_review_refuses_a_missing_transcript_a_report_and_a_service(repo, tmp_path, monkeypatch, capsys):
    """The other exit-2 cases, each saying why and writing nothing: no transcript named, `--report`
    asked for beside it, and a shared service, which keeps no such log."""
    t = two_agents(tmp_path, repo)

    assert main(["recap", "--log-review"]) == 2
    assert "needs --transcript" in capsys.readouterr().err
    assert main(["recap", "--transcript", str(t), "--log-review", "--report"]) == 2
    assert "--report does not combine" in capsys.readouterr().err
    monkeypatch.setenv("OKL_SERVICE_URL", "http://127.0.0.1:9")
    assert main(["recap", "--transcript", str(t), "--log-review"]) == 2
    assert "use the local store" in capsys.readouterr().err
    assert main(["recap", "--reviews"]) == 2
    assert "use the local store" in capsys.readouterr().err
    monkeypatch.delenv("OKL_SERVICE_URL")
    assert _rows(repo) == []


def test_log_review_writes_nothing_where_the_directory_was_never_set_up(tmp_path, monkeypatch, capsys):
    """A store URL exported does not enroll a directory: with no .okl/config.json found, exit 0 and no
    row, and the database is not even created."""
    bare = tmp_path / "bare"; bare.mkdir()
    monkeypatch.chdir(bare)
    db = tmp_path / "elsewhere.db"
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.delenv("OKL_REVIEW_LOG", raising=False)
    t = two_agents(tmp_path, repo_root(tmp_path))

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0

    assert "never set up with `okl init`" in capsys.readouterr().err
    assert not db.exists()


def test_log_review_writes_nothing_where_the_review_after_writing_is_off(repo, tmp_path, monkeypatch, capsys):
    """No review is asked for there, so none is logged: `review_after_writing` false in the config, or
    OKL_REVIEW_AFTER_WRITING=0 for one session."""
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_after_writing": False}))

    assert _log(tmp_path, repo) == 0
    assert "review after writing is off" in capsys.readouterr().err
    assert _rows(repo) == []

    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "0")
    assert _log(tmp_path, repo) == 0
    assert _rows(repo) == []
    monkeypatch.delenv("OKL_REVIEW_AFTER_WRITING")
    assert _log(tmp_path, repo) == 0
    assert len(_rows(repo)) == 1       # and with it on, the same session is logged


def test_the_log_has_its_own_off_switch(repo, tmp_path, monkeypatch, capsys):
    """`review_log: false` in the config and OKL_REVIEW_LOG=0 each stop the log and nothing else, the
    environment wins over the config, and a value okl cannot read is refused rather than taken for on."""
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_log": False}))
    assert _log(tmp_path, repo) == 0
    assert "the review log is off" in capsys.readouterr().err
    assert _rows(repo) == []

    monkeypatch.setenv("OKL_REVIEW_LOG", "1")       # the environment wins over the config
    assert _log(tmp_path, repo) == 0
    assert len(_rows(repo)) == 1
    monkeypatch.setenv("OKL_REVIEW_LOG", "0")
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    assert _log(tmp_path, repo) == 0
    assert "the review log is off" in capsys.readouterr().err

    monkeypatch.setenv("OKL_REVIEW_LOG", "of")
    assert _log(tmp_path, repo) == 2
    assert "review_log must be on or off" in capsys.readouterr().err
    assert main(["recap"]) == 0     # a setting only the log reads breaks no other command


def test_log_review_and_a_json_report_together_give_one_json_document(repo, tmp_path, capsys):
    """The status of the log goes to stderr, so stdout is the report and only the report."""
    t = two_agents(tmp_path, repo)

    assert main(["recap", "--transcript", str(t), "--log-review", "--reviews", "--format", "json"]) == 0

    got = capsys.readouterr()
    data = json.loads(got.out)
    assert data["sessions"] == 1 and data["ran"] == 1
    assert "logged session sess-1" in got.err


def test_ids_that_are_no_lesson_here_never_reach_the_row(repo, tmp_path, capsys):
    """The command filters what a command line named to the lessons this store has: the sub-agent here
    ran `okl show` on a lesson, on a word that is none, and on text that was never an id."""
    agent = [turn(40, "x1", call("c1", "Bash", command="okl show les-a; okl show passw0rd-hunter2; okl show nope"),
                  usage=(1, 1, 1, 1)),
             turn(41, "x2", call("c2", "mcp__okl__okl_get", id="another-secret"), usage=(1, 1, 1, 1))]
    t = write(tmp_path, [*start_review(), turn(120, "m2", call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
                         result(121, "tu-a", "launched", agentId="hhh")], {"hhh": (None, agent)})

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0

    (row,) = _rows(repo)
    assert row.checks[0]["lessons"] == ["les-a"]
    assert "hunter2" not in json.dumps(row.checks) and "another-secret" not in json.dumps(row.checks)


def test_a_failed_launch_is_counted_in_the_row(repo, tmp_path):
    """An Agent call that came back as an error started no sub-agent: no check, and a count in the row."""
    bad = call("tu-bad", "Agent", prompt="p")
    t = write(tmp_path, [*start_review(), turn(120, "m2", bad, usage=(1, 1, 1, 1)),
                         result(121, "tu-bad", "no such agent type", error=True)])

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0

    (row,) = _rows(repo)
    assert (row.failed_launches, row.checks) == (1, ())


def _check(lessons, *, read=True, edited=False):
    return {"agent": "a", "model": "opus", "lessons": lessons, "read": read, "edited": edited,
            "edited_files": [], "edited_outside": 0, "tests": [], "tokens": 1, "cache_read_tokens": 100}


def _fill(store):
    """Four sessions: two reviews with checks, one asked and skipped, one run without being asked."""
    store.log_review("s1", "r", asked=True, ran=True, files_changed=3, lessons_listed=10, tokens=1000,
                     cache_read_tokens=400_000, duration_s=60,
                     checks=[_check(["les-a"], edited=True), _check(["les-b"])])
    store.log_review("s2", "r", asked=True, ran=True, files_changed=2, lessons_listed=10, tokens=3000,
                     cache_read_tokens=2_000_000, duration_s=120, failed_launches=1,
                     checks=[_check(["les-a"]), _check(["les-c"], read=False),
                             _check([])])      # a sub-agent that was given no lesson
    store.log_review("s3", "r", asked=True, ran=False)
    store.log_review("s4", "r", asked=False, ran=True)         # no figures could be read
    store.log_review("s5", "other", asked=True, ran=True)      # another repo's, left out


def test_the_report_counts_what_the_log_holds(repo):
    """The report's figures, from four sessions in one repo and one in another, each hand-counted."""
    store = Client()._local_store()
    _fill(store)

    r = recap.reviews_report(store, "r")

    assert (r["sessions"], r["asked"], r["asked_and_ran"], r["asked_not_run"], r["ran_unasked"]) == (4, 3, 2, 1, 1)
    assert (r["ran"], r["ran_on_changed_files"], r["files_changed_unread"]) == (3, 2, 1)
    assert r["lessons_per_review"] == {"median": 2, "mean": 1.3, "max": 2}      # 2, 2 and 0 lessons
    assert r["reviews_without_subagent"] == 1
    # checks are sub-agents given a lesson: four; one unread; of the three read, one led to an edit
    assert (r["checks"], r["checks_read"], r["checks_unread"], r["checks_acted_on"]) == (4, 3, 1, 1)
    assert r["subagents_without_lesson"] == 1
    assert r["tokens"] == {"median": 2000, "mean": 2000.0, "max": 3000}
    assert r["cache_read_tokens"] == {"median": 1_200_000, "mean": 1_200_000.0, "max": 2_000_000}
    assert r["failed_launches"] == 1
    assert r["duration_s"] == {"median": 90, "mean": 90.0, "max": 120}
    # most checked first, then most edited, then by id; edits count over the checks that were read
    assert [(x["id"], x["checked"], x["read"], x["edited"]) for x in r["lessons"]] == [
        ("les-a", 2, 2, 1), ("les-b", 1, 1, 0), ("les-c", 1, 0, 0)]
    assert r["lessons"][0]["title"] == "the first lesson"
    assert r["lessons"][2]["title"] == "(no longer in the store)"
    assert recap.reviews_report(store, "r", since_ms=int(time.time() * 1000) + 60_000)["sessions"] == 0
    assert len(recap.reviews_report(store, "r", top=1)["lessons"]) == 1


def test_the_report_says_acted_on_not_caught_and_claude_code_only(repo, capsys):
    """An edit after a check is the review acting on a lesson; whether it fixed a real break is what the
    log cannot tell. Other agents leave no transcript, so the report says whose sessions it covers."""
    _fill(Client()._local_store())

    assert main(["recap", "--reviews"]) == 0

    out = capsys.readouterr().out
    assert "Claude Code sessions only" in out
    assert "acted on that lesson, not that it caught a break" in out
    assert "**Asked for:** 3 sessions. It ran in 2 (67%) and was skipped in 1 (1 more ran without being asked)." in out
    assert "**Reviews run:** 3, 2 against sessions that changed files (1 where" in out
    assert "**Lessons checked per review:** median 2, mean 1.3, most 2; 1 review started no sub-agent." in out
    assert "**Checks:** 4 (a sub-agent given a lesson); 1 could not be read, and of the 3 that could, 1 (33%)" in out
    # the work is the cost; the reads of the context, far larger and far cheaper, are said apart
    assert ("Tokens: median 2,000, mean 2,000, largest 3,000 (cache reads, which a call makes of the whole "
            "context and which cost far less, not counted: median 1,200,000, largest 2,000,000).") in out
    assert "Duration: median 90 s" in out and "1 Agent call came back as an error" in out
    assert "- [les-a] the first lesson: checked 2×, 1 of the 2 read followed by an edit" in out
    assert "caught" not in out.replace("not that it caught a break", "")     # nothing else claims a catch


def test_the_report_as_json_and_when_nothing_is_logged(repo, capsys):
    """An empty log says so rather than printing zeros; JSON carries the same figures; a window the
    command cannot read is refused."""
    assert main(["recap", "--reviews"]) == 0
    empty = capsys.readouterr().out
    assert "Nothing is logged for this repo yet" in empty and "Claude Code sessions only" in empty

    _fill(Client()._local_store())
    assert main(["recap", "--reviews", "--format", "json", "--limit", "2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["checks_acted_on"] == 1 and len(data["lessons"]) == 2 and data["lessons_total"] == 3
    assert main(["recap", "--reviews", "--since", "garbled"]) == 2
    assert "cannot read --since" in capsys.readouterr().err


def test_the_review_commands_say_when_nothing_is_configured(tmp_path, monkeypatch, capsys):
    """`--reviews` reads a store, so with none named it refuses as every command does; `--log-review`
    in the same place is not enrolled and says nothing worse than that nothing was logged."""
    for var in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_REVIEW_LOG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert main(["recap", "--reviews"]) == 2
    assert "NOT CONFIGURED" in capsys.readouterr().err
    assert main(["recap", "--transcript", str(tmp_path / "t.jsonl"), "--log-review"]) == 0
    assert "never set up" in capsys.readouterr().err


needs_alarm = pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM")


@needs_alarm
def test_the_log_step_is_abandoned_quietly_when_it_runs_past_its_deadline(repo, tmp_path, monkeypatch, capsys):
    """The hook kills the logger at four seconds, but a launcher can leave its child running: the
    command sets an alarm of its own, abandons the log step quietly and exits 0, and puts the alarm and
    its handler back."""
    before = signal.getsignal(signal.SIGALRM)
    monkeypatch.setattr(lessons, "LOG_DEADLINE", 1)
    monkeypatch.setattr(recap, "log_review", lambda *a, **k: time.sleep(30))
    t = two_agents(tmp_path, repo)

    start = time.monotonic()
    code = main(["recap", "--transcript", str(t), "--log-review"])

    assert code == 0 and time.monotonic() - start < 10
    got = capsys.readouterr()
    assert (got.out, got.err) == ("", "")
    assert signal.alarm(0) == 0 and signal.getsignal(signal.SIGALRM) == before     # no alarm left, handler restored
    assert _rows(repo) == []


@needs_alarm
def test_an_alarm_during_the_log_step_still_prints_the_report(repo, tmp_path, monkeypatch, capsys):
    """`--log-review --reviews`: the alarm abandons only the log step. The report is still printed, as one
    JSON document on stdout."""
    _fill(Client()._local_store())
    monkeypatch.setattr(lessons, "LOG_DEADLINE", 1)
    monkeypatch.setattr(recap, "log_review", lambda *a, **k: time.sleep(30))
    t = two_agents(tmp_path, repo)

    code = main(["recap", "--transcript", str(t), "--log-review", "--reviews", "--format", "json"])

    got = capsys.readouterr()
    assert code == 0 and got.err == ""
    assert json.loads(got.out)["sessions"] == 4      # the four rows _fill wrote; the log step wrote none


@needs_alarm
def test_the_reader_cannot_swallow_the_deadline_and_write_a_part_read_row(repo, tmp_path, monkeypatch):
    """The reader catches every Exception so it never fails a stop. The deadline is not one, so a read
    cut off by it leaves no row, rather than a row from what was read so far."""
    from okl import reviewlog

    def slow(path, reading, repo_dir, known_ids):
        reading.readable = reading.asked = True      # what it had read when the time ran out: enough for a row
        time.sleep(30)
    monkeypatch.setattr(lessons, "LOG_DEADLINE", 1)
    monkeypatch.setattr(reviewlog, "_read", slow)
    t = two_agents(tmp_path, repo)

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0

    assert _rows(repo) == []


@needs_alarm
def test_an_alarm_set_before_the_deadline_gets_its_remaining_time_back():
    """The deadline is a guest of the process's one alarm: it puts back the handler that was there, and
    an earlier alarm with the seconds it had left, rather than cancelling it."""
    before = signal.getsignal(signal.SIGALRM)
    signal.alarm(100)
    try:
        with lessons._deadline(5):
            time.sleep(0.05)
        remaining = signal.alarm(0)
    finally:
        signal.alarm(0)

    assert 95 <= remaining <= 100
    assert signal.getsignal(signal.SIGALRM) == before
    with lessons._deadline(5):
        pass
    assert signal.alarm(0) == 0                                 # and with none before, none is left after


def test_the_review_report_says_one_session_not_one_sessions():
    """Counts of one read in the singular (found running the review log end to end before 0.18.0)."""
    from okl import recap
    one = {"repo": "r", "sessions": 1, "asked": 1, "asked_and_ran": 1, "asked_not_run": 0, "ran_unasked": 0,
           "ran": 1, "ran_on_changed_files": 1, "files_changed_unread": 0,
           "lessons_per_review": {"median": 1, "mean": 1, "max": 1}, "reviews_without_subagent": 1,
           "checks": 2, "checks_read": 2, "checks_unread": 0, "checks_acted_on": 1, "subagents_without_lesson": 1,
           "tokens": None, "cache_read_tokens": None, "duration_s": None, "failed_launches": 0,
           "lessons": [{"id": "a", "title": "t", "checked": 1, "read": 1, "edited": 1}], "lessons_total": 1}
    out = recap.render_reviews(one)
    for said in ("· 1 session logged", "**Asked for:** 1 session.", "1 review started no sub-agent",
                 "(50%) was followed by an edit", "1 sub-agent the review started named no lesson and is not",
                 "(1 lesson checked)"):
        assert said in out, said
    for wrong in ("1 sessions", "1 reviews", "1 sub-agents", "1 lessons"):
        assert wrong not in out, wrong
