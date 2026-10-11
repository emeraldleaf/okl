"""Every run of a lesson's check is kept, pass or fail (okl review R3, first slice).

The stamp on a lesson records only its last pass. A check that failed left no trace, so a
check that caught a regression and one that never failed looked the same, and nothing
could say how often a lesson's check was the thing that caught a change. Failures are the
catches; this log is what any later measure of them reads.
"""
from __future__ import annotations

import json

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
])
def test_log_check_refuses_what_it_cannot_record_truthfully(tmp_path, kwargs, message):
    """A run with no command, a commit that is not an object name, or no lesson is refused."""
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

