"""Every run of a lesson's check is kept, pass or fail (okl review R3, first slice).

The stamp on a lesson records only its last pass. A check that failed left no trace, so a
check that caught a regression and one that never failed looked the same, and nothing
could say how often a lesson's check was the thing that caught a change. Failures are the
catches; this log is what any later measure of them reads.
"""
from __future__ import annotations

import contextlib
import json
import shlex
import sqlite3
import sys

import pytest

from okl import core
from okl.cli import main
from okl.client import Client
from okl.store import Store


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repo with a local store and one lesson to check."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    Client().record(id="les", type="Rule", title="refunds post after the charge", scope="repo")
    return tmp_path


def _checks(node_id: str = "les") -> list:
    return Client()._local_store().checks(node_id)


def test_a_failed_check_is_kept(repo, capsys):
    """A failing check used to leave nothing behind but a line on stderr."""
    rc = main(["verify", "les", "--run", "exit 3"])

    assert rc == 1
    [run] = _checks()
    assert (run.passed, run.command, run.outcome) == (False, "exit 3", "exit 3")
    assert "NOT stamping" in capsys.readouterr().err   # the person still hears it failed


def test_a_check_whose_signal_is_missing_is_kept_as_failed(repo):
    """Exit 0 without the expected signal is a failed check, and is kept as one."""
    assert main(["verify", "les", "--run", "echo nothing here", "--expect", "3 passed"]) == 1

    [run] = _checks()
    assert not run.passed and run.expect == "3 passed"
    assert "signal" in run.outcome and "missing" in run.outcome, run.outcome


def test_a_check_that_timed_out_is_kept_as_failed(repo):
    """A timeout is a failed check (CodeRabbit on #79), and is kept as one."""
    assert main(["verify", "les", "--run", "sleep 5", "--timeout", "1"]) == 1

    [run] = _checks()
    assert not run.passed and run.outcome == "timed out after 1s"


def test_a_passing_check_is_kept_beside_its_stamp(repo):
    """A pass is kept too: the log is every run, not only the catches."""
    assert main(["verify", "les", "--run", "echo 2 passed", "--expect", "passed"]) == 0

    [run] = _checks()
    assert (run.passed, run.outcome, run.expect) == (True, "exit 0", "passed")
    assert Client().get("les")["verified_by"].startswith("`echo 2 passed` exit 0")


def test_verify_keeps_how_long_each_run_took(repo):
    """Each run keeps its time, pass, failure and timeout alike, so `okl on-edit add --quick` can
    tell a one-second check from a three-minute suite without running anything (#467)."""
    nap = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(0.3)'"
    assert main(["verify", "les", "--run", nap]) == 0
    assert main(["verify", "les", "--run", "exit 3"]) == 1
    assert main(["verify", "les", "--run", "sleep 5", "--timeout", "1"]) == 1

    took = [r.seconds for r in _checks()]
    assert 0.3 <= took[0] < 30, took
    assert took[1] is not None and 0 <= took[1] < 30, took
    assert 1 <= took[2] < 30, took
    assert Client().get("les")["checks"][0]["seconds"] == took[0], "okl show and okl_get carry the time"


def test_reverify_keeps_the_run_of_a_stored_check_that_now_fails(repo):
    """reverify re-runs a drifted lesson's stored check through verify, so the run where
    that check catches the change is kept: the catch this log exists for."""
    import shutil
    import subprocess
    if shutil.which("git") is None:
        pytest.skip("git not available")

    def git(*a):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True,
                       env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                            "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"})

    # ARRANGE — a lesson governing state.txt, proven by a check that reads it
    git("init", "-q"); (repo / "state.txt").write_text("ok\n")
    git("add", "state.txt"); git("commit", "-q", "-m", "ok")
    Client().update("les", files="state.txt")
    assert main(["verify", "les", "--run", "grep -qx ok state.txt"]) == 0
    # ACT — the governed file changes in a way the check catches, and reverify re-runs it
    (repo / "state.txt").write_text("broken\n")
    git("commit", "-q", "-am", "break it")
    rc = main(["reverify", "--yes"])

    # ASSERT — reverify reports the failure, and the log keeps both runs, oldest first,
    # each against the commit it ran at
    assert rc == 1
    assert [(r.passed, r.outcome) for r in _checks()] == [(True, "exit 0"), (False, "exit 1")]
    assert _checks()[-1].seconds is not None, "reverify's run did not keep its time (#467)"
    heads = [subprocess.run(["git", "rev-parse", ref], cwd=repo, capture_output=True,
                            text=True).stdout.strip() for ref in ("HEAD~1", "HEAD")]
    assert [r.commit for r in _checks()] == heads

    # ACT / ASSERT (2) — a run on uncommitted edits ran no commit, so it names none
    (repo / "state.txt").write_text("ok\n")
    main(["verify", "les", "--run", "grep -qx ok state.txt"])
    assert _checks()[-1].passed and _checks()[-1].commit is None

    # ACT / ASSERT (3) — nor does a run that read a file HEAD does not have (CodeRabbit on #170)
    git("checkout", "-q", "--", "state.txt")
    (repo / "new_check.txt").write_text("ok\n")
    main(["verify", "les", "--run", "grep -qx ok new_check.txt"])
    assert _checks()[-1].passed and _checks()[-1].commit is None


def test_show_names_the_latest_failure_even_after_many_passes(repo, capsys):
    """The ten runs get lists can all be passes; the last failure is still the one that
    matters, and the latest of several (review of #170)."""
    main(["verify", "les", "--run", "exit 5"])
    main(["verify", "les", "--run", "exit 6"])
    for _ in range(core.CHECKS_SHOWN + 1):
        main(["verify", "les", "--run", "true"])
    capsys.readouterr()

    main(["show", "les"])
    shown = capsys.readouterr().out

    assert "checks: 11 passed, 2 failed; last failed" in shown and "(exit 6)" in shown, shown
    assert Client().get("les")["last_failed_check"]["outcome"] == "exit 6"


def test_show_and_get_report_the_runs(repo, capsys):
    """okl show and okl_get say how a lesson's check has fared."""
    main(["verify", "les", "--run", "true"])
    main(["verify", "les", "--run", "exit 4"])
    capsys.readouterr()

    assert main(["show", "les"]) == 0
    shown = capsys.readouterr().out
    got = Client().get("les")

    assert "checks: 1 passed, 1 failed" in shown, shown
    assert "last failed" in shown and "exit 4" in shown, shown
    assert got["check_counts"] == {"passed": 1, "failed": 1}
    assert [c["passed"] for c in got["checks"]] == [True, False]


def test_get_lists_only_the_latest_runs_but_counts_them_all(tmp_path):
    """reverify can run a check hundreds of times; get lists the latest few."""
    s = Store(f"sqlite:///{tmp_path / 'okl.db'}")
    core.record(s, id="x", type="Rule", title="x", scope="org")
    for i in range(13):
        core.log_check(s, "x", passed=i % 2 == 0, command=f"run {i}", outcome=f"exit {i % 2}")

    got = core.get(s, "x")

    assert [c["command"] for c in got["checks"]] == [f"run {i}" for i in range(3, 13)]
    assert got["check_counts"] == {"passed": 7, "failed": 6}
    s.close()


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"node_id": "nope"}, "no node"),
    ({"command": " "}, "command"),
    ({"commit": "HEAD; rm -rf ."}, "commit"),
    ({"seconds": -1.0}, "seconds"),
    ({"seconds": float("nan")}, "seconds"),
    ({"seconds": float("inf")}, "seconds"),
])
def test_log_check_refuses_what_it_cannot_record_truthfully(tmp_path, kwargs, message):
    """A run with no command, a commit that is not an object name, a time that is not a finite
    number of seconds of at least zero (#467), or no lesson is refused."""
    s = Store(f"sqlite:///{tmp_path / 'okl.db'}")
    core.record(s, id="x", type="Rule", title="x", scope="org")
    args = {"node_id": "x", "passed": False, "command": "pytest", "outcome": "exit 1", **kwargs}
    node_id = args.pop("node_id")

    with pytest.raises(ValueError, match=message):
        core.log_check(s, node_id, **args)
    s.close()


@pytest.mark.parametrize("error", ["database or disk is full", "attempt to write a readonly database"])
def test_a_store_that_cannot_take_the_run_does_not_change_the_verdict(repo, monkeypatch, capsys, error):
    """A sqlite3 error is neither a ValueError nor an outage: it escaped as a traceback,
    turned a stamped pass into exit 1, and would stop reverify at that lesson (#170)."""
    import sqlite3

    from okl import store as store_mod

    def fail(self, run):
        raise sqlite3.OperationalError(error)
    monkeypatch.setattr(store_mod._SQLiteBackend, "log_check", fail)

    assert main(["verify", "les", "--run", "true"]) == 0
    assert main(["verify", "les", "--run", "false"]) == 1
    err = capsys.readouterr().err
    assert err.count("not logged") == 2 and error in err, err


def test_a_check_that_cannot_be_logged_does_not_change_the_verdict(repo, monkeypatch, capsys):
    """Logging is a record of the check, never part of it: an older service without the
    route, or a store that refuses the write, warns and leaves the exit code alone."""
    def refuse(self, *a, **k):
        raise ValueError("the service is older than this okl client")
    monkeypatch.setattr(Client, "log_check", refuse)

    assert main(["verify", "les", "--run", "true"]) == 0
    assert main(["verify", "les", "--run", "false"]) == 1
    assert capsys.readouterr().err.count("not logged") == 2


def test_a_pass_whose_stamp_fails_is_still_logged(repo, monkeypatch):
    """The check passed whatever happens to the stamp (CodeRabbit on #170)."""
    from okl.client import OKLUnreachableError

    def down(self, *a, **k):
        raise OKLUnreachableError("the service is down")
    monkeypatch.setattr(Client, "verify", down)

    assert main(["verify", "les", "--run", "true"]) == 2
    assert [r.passed for r in _checks()] == [True]


def test_a_service_logs_checks_through_the_real_client(remote):
    """Through the client's real remote code, not by posting to the app directly."""
    core.record(remote.store, id="les", type="Rule", title="t", scope="org")

    assert main(["verify", "les", "--run", "false"]) == 1
    assert main(["verify", "les", "--run", "true"]) == 0

    assert [r.passed for r in remote.store.checks("les")] == [False, True]
    assert Client().get("les")["check_counts"] == {"passed": 1, "failed": 1}


def test_an_older_service_without_the_route_is_named(remote, monkeypatch):
    """A 404 from /check-run means a service older than this client, not a missing lesson."""
    core.record(remote.store, id="les", type="Rule", title="t", scope="org")
    remote.app.router.routes = [r for r in remote.app.router.routes
                                if getattr(r, "path", "") != "/check-run"]

    with pytest.raises(ValueError, match="older than this okl client"):
        Client().log_check("les", passed=True, command="true", outcome="exit 0")


def test_the_service_refuses_an_unknown_field(remote):
    """A closed request model, like every write the service takes."""
    r = remote.api.post("/check-run", json={"id": "x", "passed": True, "command": "t",
                                            "outcome": "exit 0", "surprise": 1})
    assert r.status_code == 422


def test_a_store_from_before_run_times_gains_the_column_on_open(tmp_path):
    """A check log written before #467 has no `seconds` column: opening the store adds it, its
    rows read back untimed, new runs keep their time, and opening it again changes nothing
    (lesson n_967ef9825472)."""
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE check_run(
        at INTEGER NOT NULL, node_id TEXT NOT NULL, passed INTEGER NOT NULL,
        command TEXT NOT NULL, outcome TEXT NOT NULL, expect TEXT, commit_id TEXT)""")
    c.execute("INSERT INTO check_run VALUES(1, 'x', 1, 'pytest -q', 'exit 0', 'passed', NULL)")
    c.commit(); c.close()

    s = Store(f"sqlite:///{db}")
    s.log_check("x", True, "pytest -q", "exit 0", expect="passed", seconds=2.5)
    s.close()
    again = Store(f"sqlite:///{db}")

    with contextlib.closing(sqlite3.connect(db)) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(check_run)")]
    assert cols.count("seconds") == 1, cols
    assert [(r.command, r.seconds) for r in again.checks("x")] == [("pytest -q", None), ("pytest -q", 2.5)]
    again.close()


def test_a_service_keeps_each_runs_time(remote):
    """Through the client's real remote code, the time reaches the service's store (#467)."""
    core.record(remote.store, id="les", type="Rule", title="t", scope="org")

    assert main(["verify", "les", "--run", "true"]) == 0

    [run] = remote.store.checks("les")
    assert run.seconds is not None and run.seconds >= 0
    assert [b.get("seconds") for p, b in remote.sent if p == "/check-run"] == [run.seconds]


def test_a_service_from_before_run_times_still_keeps_the_run(remote, capsys):
    """A service whose closed request model has no `seconds` refuses it with a 422: the client
    sends the run again without its time, so the run is kept, untimed, as one never timed, which
    `okl on-edit add --quick` never approves. Upgrading the client first must not lose the log."""
    from fastapi import Body, HTTPException
    core.record(remote.store, id="les", type="Rule", title="t", scope="org")
    known = {"id", "passed", "command", "outcome", "expect", "commit"}

    def older(body: dict = Body(...)) -> dict:  # noqa: B008 - how FastAPI declares a request body
        extra = sorted(set(body) - known)
        if extra:   # what pydantic's extra="forbid" answers
            raise HTTPException(422, detail=[{"type": "extra_forbidden", "loc": ["body", k],
                                              "msg": "Extra inputs are not permitted"} for k in extra])
        core.log_check(remote.store, body["id"], passed=body["passed"], command=body["command"],
                       outcome=body["outcome"], expect=body.get("expect"), commit=body.get("commit"))
        return {"ok": True}
    remote.app.router.routes = [r for r in remote.app.router.routes
                                if getattr(r, "path", "") != "/check-run"]
    remote.app.post("/check-run")(older)

    assert main(["verify", "les", "--run", "true"]) == 0

    assert [(r.passed, r.seconds) for r in remote.store.checks("les")] == [(True, None)]
    assert "not logged" not in capsys.readouterr().err
    posted = [b for p, b in remote.sent if p == "/check-run"]
    assert ["seconds" in b for b in posted] == [True, False], posted



@pytest.mark.parametrize(("detail", "retried"), [
    ([{"type": "extra_forbidden", "loc": ["body", "seconds"], "msg": "Zusätzliche Eingaben nicht erlaubt"}], True),
    ([{"type": "extra_forbidden", "loc": ["body", "surprise"], "msg": "seconds are fine, surprise is not"}], False),
    ("seconds is not permitted", False),
    (None, False),
])
def test_the_retry_without_a_time_reads_what_was_refused_not_the_words(detail, retried):
    """The client sends a run again without its time only when the 422's structured detail
    refused `seconds`: a translated message still retries, and a message that merely mentions
    the word, about another field or with no structure at all, does not (#467 review)."""
    from types import SimpleNamespace

    from okl.client import OKLRejectedError
    sent = []

    def post(path, body):
        sent.append(body)
        if "seconds" in body:
            # worded as _post words it, the detail inside the message
            raise OKLRejectedError(f"OKL service rejected the request (422): {detail}", status=422, detail=detail)
    me = SimpleNamespace(_post=post)
    run = {"id": "les", "passed": True, "command": "true", "outcome": "exit 0"}
    if retried:
        Client._post_check_run(me, run, 0.4)
    else:
        with pytest.raises(OKLRejectedError):
            Client._post_check_run(me, run, 0.4)
    assert ["seconds" in b for b in sent] == ([True, False] if retried else [True])


# --- what a check is claimed to cover (#524) -------------------------------------------------------
# A check that passed says the rule was true of the code that existed. Of 28 lessons that real
# changes broke, 20 had such a check (REPORT §4bm). `okl verify --covers new-code` records the
# claim that a check reads every file the rule applies to, ones not yet written included, and the
# briefing, `okl show` and `okl metric` then tell that lesson from one checked once.


def _cover(node_id: str = "les") -> str | None:
    return Client().get(node_id)["covers"]


def test_a_claim_is_kept_with_the_run_and_belongs_to_the_lesson_and_its_command(repo, capsys):
    """`--covers new-code` is recorded on the passing run. A later run of the same command that
    says nothing keeps it, as `okl reverify` and an older okl do; `--covers instance` takes it
    back; a different command is a different check and starts with no claim; and a run that
    failed claims nothing."""
    assert _cover() is None
    assert main(["verify", "les", "--run", "true", "--covers", "new-code"]) == 0
    assert _cover() == "new-code" and _checks()[-1].covers == "new-code"
    assert main(["verify", "les", "--run", "true"]) == 0
    assert _cover() == "new-code" and _checks()[-1].covers is None, "a run with no claim changes none"
    assert main(["verify", "les", "--run", "exit 3", "--covers", "new-code"]) == 1
    assert _checks()[-1].covers is None, "a failed run claims nothing"
    assert main(["verify", "les", "--run", "true", "--covers", "instance"]) == 0
    assert _cover() == "instance"
    assert main(["verify", "les", "--run", "true", "--covers", "new-code"]) == 0
    assert main(["verify", "les", "--run", "true && true"]) == 0
    assert _cover() is None, "another command is another check"
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(["verify", "les", "--run", "true", "--covers", "everything"])
    assert "invalid choice" in capsys.readouterr().err


def test_log_check_refuses_a_claim_it_does_not_know(tmp_path):
    """The store's own entry refuses a word that is no claim, so a service's caller cannot write one."""
    s = Store(f"sqlite:///{tmp_path / 'c.db'}")
    core.record(s, id="x", type="Rule", title="t", scope="org")
    with pytest.raises(ValueError, match="covers must be one of new-code, instance"):
        core.log_check(s, "x", passed=True, command="true", outcome="exit 0", covers="all")
    assert s.coverage_claims() == {}
    s.close()


def test_show_says_which_of_three_things_a_lessons_proof_is(repo, capsys):
    """`okl show` tells a lesson with no check, one checked on the code as it stood, and one whose
    check is claimed to cover new code apart, and says how to make the claim."""
    main(["show", "les"])
    assert "not proven yet" in capsys.readouterr().out
    assert main(["verify", "les", "--run", "true"]) == 0
    capsys.readouterr()
    main(["show", "les"])
    once = capsys.readouterr().out
    assert "its check covers the code as it stood" in once and "--covers new-code" in once
    assert main(["verify", "les", "--run", "true", "--covers", "new-code"]) == 0
    capsys.readouterr()
    main(["show", "les"])
    held = capsys.readouterr().out
    assert "its check is claimed to cover new code" in held and "as it stood" not in held


def test_the_briefing_marks_the_three_kinds_apart(repo, capsys):
    """In the briefing a lesson with no check is UNCHECKED, one whose check is claimed to cover
    new code says so, and one checked once carries no mark; each mark is explained once below, in
    the full briefing and in the compact one."""
    c = Client()
    c.record(id="held", type="Rule", title="refunds are held to the ledger", scope="repo", fix="post through the ledger")
    c.record(id="never", type="Rule", title="refunds never skip the audit", scope="repo", fix="write the audit row")
    assert main(["verify", "les", "--run", "true"]) == 0
    assert main(["verify", "held", "--run", "true", "--covers", "new-code"]) == 0
    capsys.readouterr()
    main(["check", "--task", "refunds post after the charge, held to the ledger, never skip the audit"])
    out = capsys.readouterr().out
    lines = {key: next(line for line in out.splitlines() if f"[{key}]" in line) for key in ("les", "held", "never")}
    assert "*(COVERS NEW CODE)*" in lines["held"] and "UNCHECKED" not in lines["held"]
    assert "*(UNCHECKED)*" in lines["never"]
    assert "COVERS" not in lines["les"] and "UNCHECKED" not in lines["les"]
    assert "1 lesson(s) marked COVERS NEW CODE" in out and "1 lesson(s) marked UNCHECKED" in out
    main(["check", "--task", "refunds post after the charge, held to the ledger, never skip the audit", "--format", "actions"])
    compact = capsys.readouterr().out
    assert "COVERS NEW CODE: that lesson's check is said to read every file" in compact, compact


def test_metric_counts_how_each_lesson_is_held(repo, capsys):
    """`okl metric` counts the lessons in scope once each, under the strongest thing true of it:
    a check claimed to cover new code, a check with files drift watches, a check that passed once,
    or none."""
    c = Client()
    c.record(id="held", type="Rule", title="a", scope="repo")
    c.record(id="watched", type="Rule", title="b", scope="repo", files="app.py")
    c.record(id="never", type="Rule", title="c", scope="repo")
    for args in (["les"], ["held", "--covers", "new-code"], ["watched"]):
        assert main(["verify", args[0], "--run", "true", *args[1:]]) == 0
    assert Client().hygiene_report()["proof"] == {
        "lessons": 4, "covers_new_code": 1, "watched": 1, "checked_once": 1, "unchecked": 1}
    capsys.readouterr()
    assert main(["metric"]) == 0
    assert ("proof: of 4 lessons in scope here, 1 have a check claimed to cover new code, 1 are watched"
            in capsys.readouterr().out)


def test_the_command_a_claim_is_kept_under_is_the_one_reverify_reads():
    """The claim is looked up by the command in the lesson's evidence, parsed in the store; the
    command line's own parse of that evidence must give the same command, or a claim would sit
    under a name nothing asks for."""
    from okl.cli.verification import _stored_check
    from okl.store import stored_command
    for evidence in ("`pytest -q` exit 0 @ 2026-11-25T10:00Z",
                     "`pytest -q -k 'a or b'` exit 0, matched 'passed' on commit abc1234 @ 2026-11-25T10:00Z",
                     "`echo '` exit 0' && true` exit 0 on commit abc1234 @ 2026-11-25T10:00Z",
                     "imported with no evidence", "", None):
        parsed = _stored_check(evidence)
        assert stored_command(evidence) == (parsed[0] if parsed else None), evidence
    # Evidence that does not end the way verify writes it: read as it always was. Text after the
    # run that is no signal leaves the command; a signal that is not a quoted string names no check.
    assert _stored_check("`pytest -q` exit 0, as recorded by hand") == ("pytest -q", None)
    assert _stored_check("`pytest -q` exit 0, matched 'pas @ 2026-11-25T10:00Z") is None
    assert _stored_check("`pytest -q` exit 0, matched 5 @ 2026-11-25T10:00Z") is None


@pytest.mark.parametrize(("run", "expect"), [
    ("pytest -q", None), ("pytest -q", "passed"),
    ("echo '` exit 0' && true", None),                    # the characters that end a run, in the command
    ("echo ok", "` exit 0"),                              # and in the signal: the second time in the evidence
    ("echo '` exit 0' && true", "` exit 0, matched 'x"),  # in both, with the words that follow a run
    ("true", "ok on commit abc1234"), ("true", "a @ 2026-11-25T10:00Z"),
])
@pytest.mark.parametrize("commit", [" on commit abc1234def0", ""])
def test_the_command_is_read_back_whole_whatever_the_signal_holds(run, expect, commit):
    """`okl verify` writes the command, the signal and the stamp into one line, and both may hold
    any text. Reading the command back from the last "` exit 0" in the line cut it short when the
    signal held those characters: `okl reverify` then listed a command nobody stored, and the
    claim kept under the real one was not found."""
    from okl.store import stored_check
    evidence = f"`{run}` exit 0" + (f", matched {expect!r}" if expect else "") + f"{commit} @ 2026-11-25T10:00Z"
    assert stored_check(evidence) == (run, expect), evidence


def test_a_claim_is_found_when_the_signal_holds_the_text_that_ends_a_run(repo):
    """The whole path, with a real run: a check whose output and --expect hold "` exit 0" keeps
    its claim, and reverify reads back the command that was run."""
    from okl.cli.verification import _stored_check
    run, expect = "echo 'the run printed ` exit 0 here'", "` exit 0"
    assert main(["verify", "les", "--run", run, "--expect", expect, "--covers", "new-code"]) == 0
    assert _stored_check(Client().get("les")["verified_by"]) == (run, expect)
    assert _cover() == "new-code"


def test_a_store_from_before_claims_gains_the_column_on_open(tmp_path):
    """A check log written before #524 has no `covers` column: opening the store adds it, its
    rows claim nothing, a new run keeps its claim, and opening it again changes nothing."""
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE check_run(
        at INTEGER NOT NULL, node_id TEXT NOT NULL, passed INTEGER NOT NULL,
        command TEXT NOT NULL, outcome TEXT NOT NULL, expect TEXT, commit_id TEXT, seconds REAL)""")
    c.execute("INSERT INTO check_run VALUES(1, 'x', 1, 'pytest -q', 'exit 0', 'passed', NULL, NULL)")
    c.commit(); c.close()

    s = Store(f"sqlite:///{db}")
    assert s.coverage_claims() == {}
    s.log_check("x", True, "pytest -q", "exit 0", covers="new-code")
    s.close()
    again = Store(f"sqlite:///{db}")
    with contextlib.closing(sqlite3.connect(db)) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(check_run)")]
    assert cols.count("covers") == 1, cols
    assert [r.covers for r in again.checks("x")] == [None, "new-code"]
    assert again.coverage_claims() == {("x", "pytest -q"): "new-code"}
    again.close()


def test_a_service_keeps_the_claim_and_briefs_with_it(remote, capsys):
    """Through the client's real remote code the claim reaches the service's store, and the
    lesson it briefs carries it, so the client's mark has something to read."""
    core.record(remote.store, id="les", type="Rule", title="refunds post after the charge", scope="org", fix="post it")

    assert main(["verify", "les", "--run", "true", "--covers", "new-code"]) == 0

    assert remote.store.coverage_claims() == {("les", "true"): "new-code"}
    assert [b.get("covers") for p, b in remote.sent if p == "/check-run"] == ["new-code"]
    capsys.readouterr()
    main(["check", "--task", "refunds post after the charge"])
    assert "[les] *(COVERS NEW CODE)*" in capsys.readouterr().out


def test_a_service_too_old_to_keep_a_claim_is_said_and_the_claim_is_not_dropped(remote, capsys):
    """A service from before #524 refuses the field. The run is not sent again without the claim,
    as it is for a run's time: a claim the person made would then vanish with exit 0. okl verify
    stamps the lesson, says the claim was not recorded, and exits 2. With no claim made, the same
    service keeps the run as before."""
    from fastapi import Body, HTTPException
    core.record(remote.store, id="les", type="Rule", title="t", scope="org")
    known = {"id", "passed", "command", "outcome", "expect", "commit", "seconds"}

    def older(body: dict = Body(...)) -> dict:  # noqa: B008 - how FastAPI declares a request body
        extra = sorted(set(body) - known)
        if extra:   # what pydantic's extra="forbid" answers
            raise HTTPException(422, detail=[{"type": "extra_forbidden", "loc": ["body", k],
                                              "msg": "Extra inputs are not permitted"} for k in extra])
        core.log_check(remote.store, body["id"], passed=body["passed"], command=body["command"],
                       outcome=body["outcome"], expect=body.get("expect"), commit=body.get("commit"))
        return {"ok": True}
    remote.app.router.routes = [r for r in remote.app.router.routes
                                if getattr(r, "path", "") != "/check-run"]
    remote.app.post("/check-run")(older)

    assert main(["verify", "les", "--run", "true", "--covers", "new-code"]) == 2
    err = capsys.readouterr().err
    assert "keeps what a check covers" in err and "--covers new-code was NOT recorded" in err, err
    assert "`okl show les` says" in err and "as it stood" not in err, "what the lesson reads as now is not guessed"
    assert remote.store.checks("les") == [], "the run is not kept with its claim cut off"
    assert remote.store.get_node("les").verified_at is not None, "the stamp is recorded all the same"
    assert main(["verify", "les", "--run", "true"]) == 0
    assert [r.covers for r in remote.store.checks("les")] == [None]


def test_a_claim_whose_answer_was_lost_is_not_said_to_be_missing(repo, monkeypatch, capsys):
    """A run that was sent and never answered may have been kept, so the claim "may not have been
    recorded"; one that could not be written "was NOT recorded". Neither says what the lesson reads
    as now: with an earlier claim on the same command, that claim still stands. Both exit 2."""
    from okl.client import OKLNoAnswerError
    assert main(["verify", "les", "--run", "true", "--covers", "new-code"]) == 0
    capsys.readouterr()

    real = Client.log_check

    def lost(self, *a, **k):
        raise OKLNoAnswerError("no answer came back")
    monkeypatch.setattr(Client, "log_check", lost)
    assert main(["verify", "les", "--run", "true", "--covers", "instance"]) == 2
    err = capsys.readouterr().err
    assert "--covers instance may not have been recorded" in err and "NOT recorded" not in err, err
    assert "`okl show les` says" in err and "as it stood" not in err, err

    def full(self, *a, **k):
        raise OSError("database or disk is full")
    monkeypatch.setattr(Client, "log_check", full)
    assert main(["verify", "les", "--run", "true", "--covers", "instance"]) == 2
    assert "--covers instance was NOT recorded" in capsys.readouterr().err
    monkeypatch.setattr(Client, "log_check", real)
    assert _cover() == "new-code", "the earlier claim stands, as the message left open"
    monkeypatch.setattr(Client, "log_check", lost)
    assert main(["verify", "les", "--run", "true"]) == 0, "with no claim asked for, a run that is not logged is still a pass"
