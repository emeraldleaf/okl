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
