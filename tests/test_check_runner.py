"""The one runner every check goes through: `okl verify`, `okl reverify` and `okl on-edit` (#441).

It runs the command in a process group of its own, so a timeout can stop the group. These hold
what that cost and what it promises: Ctrl-C and SIGTERM still stop a running check, a process
that left the group cannot hold okl past its timeout, stderr still counts toward `--expect`, a
stray byte does not crash it, and a stored command is shown escaped when it holds a hidden
character.
"""
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = shlex.quote(sys.executable)

pytestmark = pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX")


def _repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"; (repo / "src").mkdir(parents=True)
    local = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
    env = {k: v for k, v in os.environ.items() if k not in local and k != "OKL_SERVICE_URL"}
    # Named per command, in this dict, never exported to the test process.
    env.update(OKL_DATABASE_URL=f"sqlite:///{tmp_path / 'store.db'}", PYTHONPATH=str(ROOT / "src"))
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env)
    (repo / "src" / "orders.py").write_text("def get(): ...\n")
    (repo / ".okl").mkdir(); (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)
    r = _okl(repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", "orders",
             "--title", "Orders hold no BAD", "--files", "src/orders.py")
    assert r.returncode == 0, r.stderr
    return repo, env


def _okl(repo, env, *args, **extra):
    return subprocess.run([sys.executable, "-m", "okl", *args], cwd=repo, env={**env, **extra},
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_interrupting_okl_stops_the_check_it_is_running(tmp_path, sig):
    """The check's own group is outside the terminal's, so Ctrl-C reaches okl and not the check;
    okl stops the group before it exits. Before, `okl verify` then Ctrl-C left the check running
    in the background, and it wrote its file afterwards (review of #441)."""
    repo, env = _repo(tmp_path)
    (repo / "slow.py").write_text("import time\ntime.sleep(4)\nopen('late.txt', 'w')\n")
    okl = subprocess.Popen([sys.executable, "-m", "okl", "verify", "orders", "--run", f"{PY} slow.py",
                            "--expect", "never"], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.5)   # okl has started the check
    okl.send_signal(sig)
    okl.communicate(timeout=10)
    assert okl.returncode != 0
    time.sleep(4)
    assert not (repo / "late.txt").exists(), "the check outlived okl"


CLEANS_UP = {
    signal.SIGINT: "import time\ntry:\n    time.sleep(10)\nfinally:\n    open('cleaned.txt', 'w')\n",
    signal.SIGTERM: ("import signal, sys, time\n"
                     "signal.signal(signal.SIGTERM, lambda *a: (open('cleaned.txt', 'w'), sys.exit(0)))\n"
                     "time.sleep(10)\n"),
}


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_an_interrupted_check_is_passed_the_signal_and_gets_to_clean_up(tmp_path, sig):
    """okl passes Ctrl-C or SIGTERM on to the check before killing what is left, so its own cleanup
    runs (a finally, pytest's teardown, a shell trap), as when the terminal's Ctrl-C reached it;
    killing it outright first left a check's container or temporary database behind (review of
    #441)."""
    repo, env = _repo(tmp_path)
    (repo / "cleans.py").write_text(CLEANS_UP[sig])
    okl = subprocess.Popen([sys.executable, "-m", "okl", "verify", "orders", "--run", f"{PY} cleans.py",
                            "--expect", "never"], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.5)
    okl.send_signal(sig)
    okl.communicate(timeout=10)
    assert (repo / "cleaned.txt").exists(), "the check was killed before its cleanup ran"


def test_a_signal_okl_was_started_ignoring_stays_ignored(tmp_path):
    """Under nohup SIGHUP is ignored; okl leaves it so, and the check runs to its end, where
    replacing every handler made okl exit 129 and kill its check (review of #441)."""
    repo, env = _repo(tmp_path)
    (repo / "steady.py").write_text("import time\ntime.sleep(3)\nopen('done.txt', 'w')\nprint('CHECKS OK')\n")
    okl = subprocess.Popen([sys.executable, "-m", "okl", "verify", "orders", "--run", f"{PY} steady.py",
                            "--expect", "CHECKS OK"], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
    time.sleep(1.5)
    okl.send_signal(signal.SIGHUP)
    _out, err = okl.communicate(timeout=20)
    assert okl.returncode == 0, err
    assert (repo / "done.txt").exists()


def test_the_exit_handlers_go_only_over_the_default_in_the_main_thread_and_come_off_after():
    """SIGTERM and SIGHUP raise while a check runs only where they had their default action; an
    ignored one or a host's own handler is kept; both are restored after; and a worker thread,
    where Python cannot set handlers, runs the check without trying."""
    import threading

    from okl.cli import verification as v
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}

    def mine(*_a):
        return None
    try:
        for s in before:
            signal.signal(s, signal.SIG_DFL)
        with v._exit_signals_raise():
            assert [signal.getsignal(s) for s in before] == [v._raise_exit, v._raise_exit]
        assert [signal.getsignal(s) for s in before] == [signal.SIG_DFL, signal.SIG_DFL]
        signal.signal(signal.SIGTERM, mine); signal.signal(signal.SIGHUP, signal.SIG_IGN)
        with v._exit_signals_raise():
            assert signal.getsignal(signal.SIGTERM) is mine
            assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        seen: list = []

        def worker():
            with v._exit_signals_raise():
                seen.append(signal.getsignal(signal.SIGTERM))
        th = threading.Thread(target=worker); th.start(); th.join()
        assert seen == [signal.SIG_DFL]
    finally:
        for s, h in before.items():
            signal.signal(s, h)


def test_a_process_that_left_the_group_cannot_hold_okl_past_its_timeout(tmp_path):
    """A helper started in its own session keeps the output pipe open; okl stops reading two
    seconds after the timeout instead of waiting for it (15 s for a 2 s timeout before, forever
    for a server: review of #441)."""
    repo, env = _repo(tmp_path)
    (repo / "daemon.py").write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'], start_new_session=True)\n"
        "time.sleep(30)\n")
    started = time.monotonic()
    r = _okl(repo, env, "verify", "orders", "--run", f"{PY} daemon.py", "--expect", "ok", "--timeout", "1")
    elapsed = time.monotonic() - started
    assert r.returncode == 1 and "TIMED OUT" in r.stderr, r.stderr
    assert elapsed < 8, f"okl waited {elapsed:.1f}s on a process outside the check's group"


def test_stderr_counts_toward_expect_and_a_stray_byte_does_not_crash_the_run(tmp_path):
    """stdout and stderr are read as one stream, so a signal printed on stderr matches; and a
    byte that is not UTF-8 is replaced, where before it ended the run with a decode error."""
    repo, env = _repo(tmp_path)
    on_stderr = f"{PY} -c \"import sys; print('CHECKS OK', file=sys.stderr)\""
    r = _okl(repo, env, "verify", "orders", "--run", on_stderr, "--expect", "CHECKS OK")
    assert r.returncode == 0, r.stderr
    stray = f"{PY} -c \"import sys; sys.stdout.buffer.write(b'\\\\xff\\\\xfe CHECKS OK\\\\n')\""
    r = _okl(repo, env, "verify", "orders", "--run", stray, "--expect", "CHECKS OK")
    assert r.returncode == 0, r.stderr


def test_reverify_shows_a_stored_command_that_could_hide_escaped(tmp_path):
    """reverify lists each stored command before running it; one holding a carriage return and an
    erase-line code is shown escaped, so the person sees what would run (review of #441)."""
    repo, env = _repo(tmp_path)
    spoof = "echo CHECKS OK #\r\x1b[2K      pytest -q"
    assert _okl(repo, env, "verify", "orders", "--run", spoof, "--expect", "CHECKS OK").returncode == 0
    (repo / "src" / "orders.py").write_text("def get(): return 1\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "change"], check=True, env=env)
    r = _okl(repo, env, "reverify", "--dry-run")
    assert "\x1b" not in r.stdout and "\r" not in r.stdout, r.stdout
    assert repr(spoof) in r.stdout, r.stdout


def test_reverify_shows_a_lesson_id_that_could_hide_escaped(tmp_path):
    """An id is not screened when it is recorded, and reverify printed it raw before its question:
    `x] python3 -m pytest -q` and a conceal code hid the real command and the prompt that follows
    (review of #441). The id and title are shown escaped too."""
    repo, env = _repo(tmp_path)
    lid = "x] python3 -m pytest -q\x1b[8m"
    r = _okl(repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", lid, "--title", "t\x1b[8m",
             "--files", "src/orders.py")
    assert r.returncode == 0, r.stderr
    assert _okl(repo, env, "verify", lid, "--run", "echo CHECKS OK", "--expect", "CHECKS OK").returncode == 0
    (repo / "src" / "orders.py").write_text("def get(): return 1\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "change"], check=True, env=env)
    out = _okl(repo, env, "reverify", "--dry-run").stdout
    assert "\x1b" not in out and repr(lid) in out, out


def test_a_second_interrupt_in_the_grace_still_stops_the_check(tmp_path):
    """Ctrl-C pressed twice: the second, inside the two seconds okl gives the check to clean up,
    ended okl with the check still running, and it wrote its file afterwards (review of #441). It
    now cuts the grace short and stops the group."""
    repo, env = _repo(tmp_path)
    (repo / "stubborn.py").write_text(
        "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\ntime.sleep(6)\nopen('late.txt', 'w')\n")
    okl = subprocess.Popen([sys.executable, "-m", "okl", "verify", "orders", "--run", f"{PY} stubborn.py",
                            "--expect", "never"], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.5)
    okl.send_signal(signal.SIGINT)
    time.sleep(0.5)
    if okl.poll() is None:
        okl.send_signal(signal.SIGINT)
    okl.communicate(timeout=10)
    time.sleep(6)
    assert not (repo / "late.txt").exists(), "the check outlived a second Ctrl-C"


def test_nothing_shown_before_a_question_carries_a_control_character(tmp_path):
    """Every line okl prints before it asks to run stored commands, for reverify and for on-edit,
    rendered with a hostile id, title and command: no escape code or carriage return reaches the
    terminal. Sites were fixed one at a time (#441's reviews found four), so this holds them all."""
    repo, env = _repo(tmp_path)
    hostile = {
        "x] python3 -m pytest -q\r\x1b[8m": ("t\x1b[8m", None),                       # no stored check
        "y\x1b[2K": ("u\r\x1b[8m", "echo CHECKS OK #\r\x1b[2K      pytest -q"),       # everything hostile
        "z\x1b[8m": ("a plain title", "echo CHECKS OK"),                               # only the id
    }
    for lid, (title, run) in hostile.items():
        r = _okl(repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", lid, "--title", title,
                 "--files", "src/orders.py")
        assert r.returncode == 0, r.stderr
        if run:
            assert _okl(repo, env, "verify", lid, "--run", run, "--expect", "CHECKS OK").returncode == 0
    (repo / "src" / "orders.py").write_text("def get(): return 1\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "change"], check=True, env=env)

    shown = [_okl(repo, env, "reverify", "--dry-run"), _okl(repo, env, "on-edit"),
             *(_okl(repo, env, "on-edit", "add", lid) for lid in hostile)]
    for r in shown:
        for stream in (r.stdout, r.stderr):
            assert "\x1b" not in stream and "\r" not in stream, (r.args, stream)
