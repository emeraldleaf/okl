"""A shared service that stalls, drops the connection or answers garbage fails the check
closed, in time.

Incident (okl review R10, reproduced on 0.8.1): the client caught only urllib's HTTPError
and URLError. urllib wraps a failure to connect in URLError, but a service that accepts
the connection and then never answers raises a bare TimeoutError, and one that hangs up
raises ConnectionResetError or http.client.RemoteDisconnected. `okl check` died on those
with a traceback and exit 1. Worse, each try waited 10 s and the prompt hook tries three
times, about 31 s in all, while Claude Code cancels a UserPromptSubmit hook after 30 s and
then lets the prompt through: the agent started unbriefed, which is the fail-open the hook
exists to prevent.

The review of that fix found three more ways through. A reply that is not HTTP, or is cut
off mid-body, raises an http.client error that is not an OSError, so it still escaped as a
traceback. The timeout applies to each address a host resolves to, so a dual-stack host
whose addresses both drop the connection took 10 s a try and the hook ran 31.5 s anyway.
And these errors arrive only after the request was sent, so `okl record` reporting
"NOT RECORDED" for one could be wrong, and a retry then stored the lesson twice.
"""
import contextlib
import http.client
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


def _replying(raw: bytes) -> type[BaseHTTPRequestHandler]:
    class _Replies(BaseHTTPRequestHandler):
        """Reads the whole request, writes `raw` (nothing at all is a hang-up), and closes."""

        def _reply(self):
            # Read the body too: closing with unread bytes sends a reset, which can reach
            # the client while it is still sending, where urllib wraps it in URLError and
            # the unwrapped failure these tests are about would never happen.
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.wfile.write(raw)
            self.close_connection = True

        def do_POST(self):
            self._reply()

        def do_GET(self):
            self._reply()

    return _Replies


@contextlib.contextmanager
def _service_that_replies(raw: bytes):
    # TCPServer, not HTTPServer: HTTPServer looks up the host's FQDN on bind, which can
    # stall for seconds on a machine with slow reverse DNS.
    server = socketserver.TCPServer(("127.0.0.1", 0), _replying(raw))
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


# What OKL_SERVICE_URL pointed at the wrong port can get back: an SSH banner, say.
NOT_HTTP = b"SSH-2.0-OpenSSH_9.6\r\n"
# A reply that promises 500 bytes and stops after five: a proxy or service dying mid-answer.
CUT_SHORT = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
             b"Content-Length: 500\r\n\r\n{\"res")

DEAD_SERVICES = {"stalls": _service_that_stalls,
                 "hangs up": lambda: _service_that_replies(b""),
                 "is not HTTP": lambda: _service_that_replies(NOT_HTTP),
                 "cuts its reply short": lambda: _service_that_replies(CUT_SHORT)}
# Both verbs: _post carries the briefing, _get carries drift (/nodes) and the metrics.
CALLS = {"POST /check": lambda c: c.check("add a refund endpoint"),
         "GET /nodes": lambda c: c.all_nodes()}


def _okl_env(tmp_path, url):
    """The environment for one okl command against `url`: OKL_SERVICE_URL on this command
    only, a temporary HOME, and nothing else that could name a store."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path),
           "PATH": "/usr/bin:/bin"}
    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        env.pop(k, None)
    env["OKL_SERVICE_URL"] = url
    return env


def _run_okl(tmp_path, url, *argv):
    """Run okl as a separate process, as a hook does, so an exception that escapes shows up
    as the traceback and exit code the caller would read rather than as a pytest error. The
    timeout is shortened before main() runs, so a stalled service costs a fraction of a second."""
    run_okl = ("import sys, okl.client; okl.client._HTTP_TIMEOUT_S = 0.2\n"
               "from okl.cli import main; raise SystemExit(main(sys.argv[1:]))")
    return subprocess.run([sys.executable, "-c", run_okl, *argv], cwd=tmp_path,
                          env=_okl_env(tmp_path, url), text=True, capture_output=True, timeout=30)


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
    assert "no full reply came within 0.2 s" in str(caught.value), caught.value
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
    with DEAD_SERVICES["hangs up"]() as url:
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


@pytest.mark.parametrize("call", list(CALLS))
@pytest.mark.parametrize("reply", ["is not HTTP", "cuts its reply short"])
def test_a_service_whose_reply_is_not_http_or_is_cut_short_is_unreachable(
        tmp_path, monkeypatch, reply, call):
    """BadStatusLine and IncompleteRead are http.client errors, not OSErrors, so they escaped
    the first R10 fix as a traceback and exit 1, and the hook relayed the first 1,500 bytes
    of that traceback, which stopped before the line saying what went wrong."""
    from okl.client import Client, OKLUnreachableError

    # ARRANGE — a service that reads the request and answers with something unusable
    monkeypatch.chdir(tmp_path)
    with DEAD_SERVICES[reply]() as url:
        c = Client(config={"repo": "r", "service_url": url})

        # ACT
        with pytest.raises(OKLUnreachableError) as caught:
            CALLS[call](c)

    # ASSERT (1) — reported as an outage, naming the service and what came back
    message = str(caught.value)
    assert url in message, message
    assert "not HTTP or was cut short" in message, message
    # (2) it was the protocol error the OSError handler missed, kept as the cause
    assert isinstance(caught.value.__cause__, http.client.HTTPException), repr(caught.value.__cause__)
    # (3) one line, whatever the service sent: the CLI prints it under its refusal, and a
    # banner's own line breaks would split it
    assert "\n" not in message, repr(message)
    assert "\r" not in message, repr(message)


@pytest.mark.parametrize("dead", list(DEAD_SERVICES))
def test_okl_check_against_a_dead_service_exits_2_with_a_reason_not_a_traceback(tmp_path, dead):
    """What the prompt hook actually saw: a traceback and exit 1 from `okl check`."""
    # ARRANGE — an empty directory with a temporary HOME, so nothing but the dead service
    # could answer
    with DEAD_SERVICES[dead]() as url:

        # ACT
        r = _run_okl(tmp_path, url, "check", "--task", "add an endpoint", "--format", "hook")

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


@pytest.mark.parametrize("command", ["record", "verify"])
def test_a_write_the_service_took_and_never_answered_is_not_reported_as_lost(tmp_path, command):
    """A stall or hang-up reaches the client only after urllib has sent the whole request,
    so the service may have stored the write. `okl record` said "NOT RECORDED", and recording
    the lesson again without --id stored it a second time under a new id."""
    # ARRANGE — a service that takes the request and never answers
    argv = {"record": ["record", "--type", "Rule", "--scope", "org", "--title", "a lesson"],
            "verify": ["verify", "n_0123456789ab", "--run", "true"]}[command]
    with _service_that_stalls() as url:

        # ACT
        r = _run_okl(tmp_path, url, *argv)

    # ASSERT (1) — still a failure, so a script or hook does not take it as done
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    # (2) it does not claim the write was lost, which is what sent people to repeat it
    assert "not recorded" not in r.stderr.lower(), r.stderr
    # (3) it says the write may have gone through, and how to repeat it safely
    assert "may have" in r.stderr, r.stderr
    if command == "record":
        assert "okl search" in r.stderr, r.stderr   # look before recording a second copy
    else:
        assert "again is safe" in r.stderr, r.stderr  # a second stamp of the same lesson


def test_the_prompt_hook_does_not_retry_a_try_that_failed_slowly(tmp_path):
    """The retry is for a local store rebuilt in about a second. Against a service that
    stalls, each try took the whole timeout once for every address the host resolves to,
    and the hook made three: a dual-stack host whose firewall drops the connection held it
    31.5 s, past Claude Code's 30 s limit, and the prompt went through unbriefed."""
    import json

    # ARRANGE — an okl that fails after two seconds, as one stalled on the service would,
    # and logs each call so the count is the number of tries
    (tmp_path / ".okl").mkdir(); (tmp_path / ".okl" / "config.json").write_text('{"repo": "t"}')
    stub, calls = tmp_path / "okl", tmp_path / "calls"
    calls.write_text("")
    stub.write_text(f"#!/bin/sh\necho call >> '{calls}'\nsleep 2\n"
                    "echo 'OKL UNREACHABLE: no full reply came within 5 s' >&2; exit 2\n")
    stub.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "OKL_BIN": str(stub), "CLAUDE_PROJECT_DIR": str(tmp_path)}

    # ACT
    r = subprocess.run(["bash", str(PROMPT_HOOK)], cwd=tmp_path, text=True, env=env,
                       input=json.dumps({"prompt": "x"}), capture_output=True, timeout=60)

    # ASSERT (1) — the prompt is blocked, with okl's reason relayed
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "no full reply came within 5 s" in r.stderr, r.stderr
    # (2) after one try: a slow failure is an outage, and retrying it is what overran the
    # limit (a quick failure is still retried; test_scaffold covers that)
    assert len(calls.read_text().splitlines()) == 1, calls.read_text()


def test_the_prompt_hook_finishes_before_claude_code_cancels_it():
    """Three tries at 10 s each came to about 31 s, past Claude Code's 30 s limit on a
    UserPromptSubmit hook, so the hook was cancelled and the prompt went through unbriefed.

    The retry count, the pause, and the duration past which a try is not retried are read
    from the hook itself, so changing any of them, or the timeout, fails here instead of
    quietly reopening the fail-open. The model: quick failures are retried, then one slow
    try ends the loop. urllib's timeout is not a limit on the whole call: it applies to each
    connect and each read, and a connect is tried once per address the host resolves to,
    so a slow try is budgeted as two stalled addresses (an A and an AAAA record behind a
    firewall that drops rather than refuses). What no per-socket timeout bounds, a DNS
    lookup that hangs or a service that sends a byte every few seconds, is not covered.
    """
    from okl.client import _HTTP_TIMEOUT_S

    # ARRANGE — the retry loop as the hook ships it (the repo's own copies are held
    # byte-identical to this one by test_mirror_files_identical)
    hook = PROMPT_HOOK.read_text()
    loop = re.search(r"^for attempt in ([0-9 ]+); do$", hook, re.MULTILINE)
    pause = re.search(r"&& sleep ([0-9.]+)$", hook, re.MULTILINE)
    quick = re.search(r"^\s*\[ \$\(\(SECONDS - started\)\) -ge ([0-9]+) \] && break$", hook, re.MULTILINE)
    assert loop, "the hook's retry loop changed shape; re-derive this budget from it"
    assert pause, "the hook's pause between tries changed shape; re-derive this budget"
    assert quick, "the hook no longer stops after a slow try; three of them overran Claude Code's limit"
    attempts = len(loop.group(1).split())
    # SECONDS counts whole seconds, so a try the hook retried took less than this.
    quick_try_s = int(quick.group(1))
    stalled_addresses = 2
    # Starting okl and the hook's own python3 calls take about 0.1 s each; a second for
    # each leaves room for a slow or busy machine.
    start_allowance_s = 1.0
    hook_prelude_s = 1.0

    # ACT — the longest the hook can take: quick failures until the last try, which stalls
    slow_try_s = stalled_addresses * _HTTP_TIMEOUT_S + start_allowance_s
    worst_case_s = (hook_prelude_s + (attempts - 1) * (quick_try_s + float(pause.group(1)))
                    + slow_try_s)

    # ASSERT — the hook ends, and blocks, before Claude Code gives up on it
    assert worst_case_s < CLAUDE_CODE_PROMPT_HOOK_TIMEOUT_S, (
        f"{attempts - 1} quick tries (< {quick_try_s} s each, then a {pause.group(1)} s pause) "
        f"+ one try stalled on {stalled_addresses} addresses at {_HTTP_TIMEOUT_S} s each = "
        f"{worst_case_s} s, which Claude Code cuts off at {CLAUDE_CODE_PROMPT_HOOK_TIMEOUT_S} s "
        f"and lets the prompt through unbriefed")
