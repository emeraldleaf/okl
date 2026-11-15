"""The Stop hook's side of the review log (#464).

At a stop after the first, the hook runs `okl recap --transcript <path> --log-review` and nothing
else: it prints nothing, it cannot change the exit code, and it is cut off after a few seconds, so
a slow parse or a store that will not open costs a missed row and never a held stop. The okl
here is a stub that records its calls, so only the hook's side is tested; the parser and the
command are in test_review_log.py.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"


def _stop_env(tmp_path: Path, behavior: str):
    """A repo the hook will ask in, and an okl that records every call and does `behavior` for the
    log call, so the hook's side of it can be tested without the parser."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "hookrepo"; (r / ".okl").mkdir(parents=True)
    (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "dirty.txt").write_text("an uncommitted change, so the Stop hook has a reason to ask")
    markers = tmp_path / "markers"; markers.mkdir()
    log = tmp_path / "calls.log"
    stub = tmp_path / "okl-stub"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\ncase "$*" in *--log-review*) {behavior};; esac\nexit 0\n')
    stub.chmod(0o755)
    transcript = tmp_path / "sess.jsonl"
    transcript.write_text("{}\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(markers), "OKL_BIN": str(stub),
           "CLAUDE_PROJECT_DIR": str(r)}

    def stop(active: bool, session: str = "s1", path: Path | None = transcript):
        payload = {"session_id": session, "stop_hook_active": active}
        if path is not None:
            payload["transcript_path"] = str(path)
        return subprocess.run(["bash", str(HOOK)], cwd=r, text=True, capture_output=True, env=env,
                              input=json.dumps(payload), timeout=60)

    def calls():
        return log.read_text().splitlines() if log.exists() else []

    return stop, calls, transcript


def test_the_hook_logs_at_a_later_stop_and_never_at_the_first(tmp_path):
    """The first stop is blocked with the question and logs nothing, since the review has not run.
    The stop after it (stop_hook_active) and any later one log, print nothing and let the session end."""
    stop, calls, transcript = _stop_env(tmp_path, "exit 0")

    first = stop(False)
    assert first.returncode == 2 and "ENCODING LOOP" in first.stderr
    assert not any("--log-review" in c for c in calls())

    after_block = stop(True)
    assert after_block.returncode == 0 and (after_block.stdout, after_block.stderr) == ("", "")
    later = stop(False)    # the marker exists now, and a session can stop again
    assert later.returncode == 0 and (later.stdout, later.stderr) == ("", "")
    logged = [c for c in calls() if "--log-review" in c]
    assert logged == [f"recap --transcript {transcript} --log-review"] * 2


def test_the_hook_logs_nothing_without_a_readable_transcript(tmp_path):
    """With no transcript path in the payload, or one that is not there, there is nothing to read."""
    stop, calls, _ = _stop_env(tmp_path, "exit 0")

    assert stop(True, path=None).returncode == 0
    assert stop(True, path=tmp_path / "gone.jsonl").returncode == 0

    assert not any("--log-review" in c for c in calls())


def test_a_failing_logger_changes_nothing_the_agent_sees(tmp_path):
    """The logger's output goes nowhere and its exit code is not the hook's, whether it is an okl too
    old to know the flag or a store that will not open."""
    stop, calls, _ = _stop_env(tmp_path, 'echo "okl: error: unrecognized arguments: --log-review" >&2; '
                                         'echo boom; exit 2')

    r = stop(True)

    assert r.returncode == 0 and (r.stdout, r.stderr) == ("", "")
    assert any("--log-review" in c for c in calls())


def test_a_logger_that_hangs_is_cut_off_and_never_holds_the_stop(tmp_path):
    """Even one that ignores the first signal: the hook ends the stop within seconds, silent, exit 0."""
    stop, calls, _ = _stop_env(tmp_path, "trap '' TERM; sleep 8")

    start = time.monotonic()
    r = stop(True)
    took = time.monotonic() - start

    assert r.returncode == 0 and (r.stdout, r.stderr) == ("", "")
    assert any("--log-review" in c for c in calls())
    assert took < 7.5, f"the stop was held {took:.1f}s by a hung logger"


def test_the_hook_in_this_repo_and_the_one_okl_ships_are_the_same_file():
    """The mirror test covers every hook; this one names the file the log rides on, with its stamp."""
    root = Path(__file__).resolve().parents[1]
    shipped = (root / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh").read_bytes()
    assert (root / "hooks" / "stop-okl-encode.sh").read_bytes() == shipped
    assert (root / ".claude" / "hooks" / "stop-okl-encode.sh").read_bytes() == shipped
    assert b"--log-review" in shipped
