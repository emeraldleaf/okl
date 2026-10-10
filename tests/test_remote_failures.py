"""A shared service that stalls or drops the connection fails the check closed, in time.

Incident (okl review R10, reproduced on 0.8.1): the client caught only urllib's HTTPError
and URLError. urllib wraps a failure to connect in URLError, but a service that accepts
the connection and then never answers raises a bare TimeoutError, and one that hangs up
raises ConnectionResetError or http.client.RemoteDisconnected. `okl check` died on those
with a traceback and exit 1. Worse, each try waited 10 s and the prompt hook tries three
times, about 31 s in all, while Claude Code cancels a UserPromptSubmit hook after 30 s and
then lets the prompt through: the agent started unbriefed, which is the fail-open the hook
exists to prevent.
"""
import contextlib
import os
import re
import socket
import socketserver
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROMPT_HOOK = ROOT / "src" / "okl" / "scaffold" / "hooks" / "userpromptsubmit-okl-check.sh"
# Claude Code's default for a command hook on UserPromptSubmit; after it, the hook is
# cancelled and the prompt goes ahead without the hook's output.
CLAUDE_CODE_PROMPT_HOOK_TIMEOUT_S = 30


@contextlib.contextmanager
def _service_that_stalls():
    """A listener that never accepts. The kernel completes the handshake and buffers the
    request anyway, so the client connects, sends, and waits for an answer that never comes."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"


class _HangsUp(BaseHTTPRequestHandler):
    """Reads the whole request, then closes the connection without answering."""

    def _hang_up(self):
        # Read the body too: closing with unread bytes sends a reset, which can reach the
        # client while it is still sending, where urllib wraps it in URLError and the
        # unwrapped failure this test is about would never happen.
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.close_connection = True

    def do_POST(self):
        self._hang_up()

    def do_GET(self):
        self._hang_up()


@contextlib.contextmanager
def _service_that_hangs_up():
    # TCPServer, not HTTPServer: HTTPServer looks up the host's FQDN on bind, which can
    # stall for seconds on a machine with slow reverse DNS.
    server = socketserver.TCPServer(("127.0.0.1", 0), _HangsUp)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


DEAD_SERVICES = {"stalls": _service_that_stalls, "hangs up": _service_that_hangs_up}
# Both verbs: _post carries the briefing, _get carries drift (/nodes) and the metrics.
CALLS = {"POST /check": lambda c: c.check("add a refund endpoint"),
         "GET /nodes": lambda c: c.all_nodes()}


@pytest.mark.parametrize("call", list(CALLS))
def test_a_service_that_accepts_and_never_answers_is_unreachable_within_the_timeout(
        tmp_path, monkeypatch, call):
    """The stalled read surfaced as a bare TimeoutError, after 10 s, per try."""
    from okl import client as client_mod
    from okl.client import Client, OKLUnreachableError

    # ARRANGE — a service that takes the connection and then says nothing, and a short
    # timeout so the test waits a fraction of a second rather than the real budget
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(client_mod, "_HTTP_TIMEOUT_S", 0.2)
    with _service_that_stalls() as url:
        c = Client(config={"repo": "r", "service_url": url})

        # ACT
        started = time.monotonic()
        with pytest.raises(OKLUnreachableError) as caught:
            CALLS[call](c)
        elapsed = time.monotonic() - started

    # ASSERT (1) — the failure is the one every caller already fails closed on, and its
    # message says where and why, so the person can tell a stall from a refusal
    assert url in str(caught.value), caught.value
    assert "no response within 0.2 s" in str(caught.value), caught.value
    # (2) the original exception is kept as the cause, for whoever has to debug it
    assert isinstance(caught.value.__cause__, TimeoutError)
    # (3) the wait is bounded by _HTTP_TIMEOUT_S, the value the hook budget is computed
    # from, not by some other timeout hard-coded at a call site
    assert elapsed < 2.0, f"waited {elapsed:.1f}s against a 0.2 s timeout"


@pytest.mark.parametrize("call", list(CALLS))
def test_a_service_that_hangs_up_without_answering_is_unreachable(tmp_path, monkeypatch, call):
    """A dropped connection surfaced as a bare RemoteDisconnected or ConnectionResetError."""
    from okl.client import Client, OKLUnreachableError

    # ARRANGE — a service that reads the request and closes the connection
    monkeypatch.chdir(tmp_path)
    with _service_that_hangs_up() as url:
        c = Client(config={"repo": "r", "service_url": url})

        # ACT
        with pytest.raises(OKLUnreachableError) as caught:
            CALLS[call](c)

    # ASSERT (1) — reported as unreachable, naming the service
    assert url in str(caught.value), caught.value
    # (2) and it really was the unwrapped socket error, the case that used to escape:
    # a URLError was already translated before this fix and proves nothing here
    cause = caught.value.__cause__
    assert isinstance(cause, OSError), repr(cause)
    assert not isinstance(cause, URLError), repr(cause)


@pytest.mark.parametrize("dead", list(DEAD_SERVICES))
def test_okl_check_against_a_dead_service_exits_2_with_a_reason_not_a_traceback(tmp_path, dead):
    """What the prompt hook actually saw: a traceback and exit 1 from `okl check`.

    Run as a separate process, as the hook runs it, so an exception that escapes shows up
    as the traceback and exit code the hook would read rather than as a pytest error.
    """
    # ARRANGE — OKL_SERVICE_URL on this one command only, in an empty directory with a
    # temporary HOME, so nothing but the dead service could answer. The timeout is
    # shortened before main() runs so the stalled case takes a fraction of a second.
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path),
           "PATH": "/usr/bin:/bin"}
    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        env.pop(k, None)
    run_okl = ("import sys, okl.client; okl.client._HTTP_TIMEOUT_S = 0.2\n"
               "from okl.cli import main; raise SystemExit(main(sys.argv[1:]))")
    with DEAD_SERVICES[dead]() as url:
        env["OKL_SERVICE_URL"] = url

        # ACT
        r = subprocess.run([sys.executable, "-c", run_okl, "check", "--task", "add an endpoint",
                            "--format", "hook"], cwd=tmp_path, env=env, text=True,
                           capture_output=True, timeout=30)

    # ASSERT (1) — exit 2, okl's "could not run". It was 1, which okl's contract keeps for
    # a command that ran and found something, so the hook misreported it as an okl error.
    assert r.returncode == 2, (r.returncode, r.stderr)
    # (2) nothing on stdout, which the hook would hand the model as a briefing
    assert r.stdout == "", r.stdout
    # (3) a reason a person can act on, not a Python traceback: the refusal, then one
    # line naming the service and what went wrong
    assert "Traceback" not in r.stderr, r.stderr
    lines = r.stderr.strip().splitlines()
    assert len(lines) == 2, r.stderr
    assert "UNREACHABLE" in lines[0], r.stderr
    assert f"OKL service unreachable at {url}/check: " in lines[1], r.stderr


def test_the_prompt_hooks_retries_finish_before_claude_code_cancels_the_hook():
    """Three tries at 10 s each came to about 31 s, past Claude Code's 30 s limit on a
    UserPromptSubmit hook, so the hook was cancelled and the prompt went through unbriefed.

    The retry count and the pause between tries are read from the hook itself, so raising
    either, or the timeout, fails here instead of quietly reopening the fail-open. The
    bound covers one stalled read per try, the failure this file is about; per try, only
    one call reaches the service (the hook's format fallbacks rerun okl only after its
    argument parser refused, which is instant).
    """
    from okl.client import _HTTP_TIMEOUT_S

    # ARRANGE — the retry loop as the hook ships it (the repo's own copies are held
    # byte-identical to this one by test_mirror_files_identical)
    hook = PROMPT_HOOK.read_text()
    loop = re.search(r"^for attempt in ([0-9 ]+); do$", hook, re.MULTILINE)
    pause = re.search(r"&& sleep ([0-9.]+)$", hook, re.MULTILINE)
    assert loop, "the hook's retry loop changed shape; re-derive this budget from it"
    assert pause, "the hook's pause between tries changed shape; re-derive this budget"
    attempts = len(loop.group(1).split())
    # Starting okl and the hook's own python3 calls take about 0.1 s each; a second per try
    # leaves room for a slow or busy machine.
    start_allowance_s = 1.0

    # ACT — the longest the hook can take when every try stalls
    worst_case_s = (attempts * (_HTTP_TIMEOUT_S + start_allowance_s)
                    + (attempts - 1) * float(pause.group(1)))

    # ASSERT — the hook ends, and blocks, before Claude Code gives up on it
    assert worst_case_s < CLAUDE_CODE_PROMPT_HOOK_TIMEOUT_S, (
        f"{attempts} tries x ({_HTTP_TIMEOUT_S} s timeout + {start_allowance_s} s start) "
        f"+ pauses = {worst_case_s} s, which Claude Code cuts off at "
        f"{CLAUDE_CODE_PROMPT_HOOK_TIMEOUT_S} s and lets the prompt through unbriefed")
