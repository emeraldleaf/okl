"""The prompt hook's unbriefed paths (okl review R21).

A prompt that reaches the agent without a briefing must say so, to the person and to the
agent. And a pinned okl that cannot start must not block a prompt that a working okl on
PATH could brief (#152).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "userpromptsubmit-okl-check.sh"
BARE = "/usr/bin:/bin"   # a system python3 to parse JSON, and no okl


def _stub(path: Path, body: str, shebang: str = "#!/bin/sh") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{shebang}\n{body}\n"); path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path):
    """An enrolled repo (it has .okl/config.json), so the hook does not step aside."""
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    r = tmp_path / "repo"; (r / ".okl").mkdir(parents=True)
    return r


def _pin(repo: Path, okl_bin: str) -> None:
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "t", "okl_bin": okl_bin}))


def _prompt(repo: Path, path: str = BARE, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOK)], cwd=repo, text=True, capture_output=True,
                          input=json.dumps({"prompt": "add a refund endpoint"}),
                          env={"PATH": path, "HOME": str(repo.parent), **env})


def _hook_json(r: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"stdout is not the hook's JSON: {r.stdout!r} (stderr {r.stderr!r})") from None


# --- #152: a pinned okl that cannot start -------------------------------------------------

def test_a_pin_whose_interpreter_is_gone_falls_through_to_okl_on_path(repo, tmp_path):
    """A venv okl whose python was removed still exists and is executable, so the pin was
    accepted and the hook blocked on its exit 126, with a working okl on PATH (#152)."""
    broken = _stub(tmp_path / "old venv" / "bin" / "okl", "", shebang="#!/nonexistent/python3.11")
    on_path = _stub(tmp_path / "bin" / "okl", 'echo "PATH BRIEFING $1"')
    _pin(repo, str(broken))

    r = _prompt(repo, path=f"{on_path.parent}:{BARE}")

    assert r.returncode == 0, r.stderr
    assert "PATH BRIEFING check" in r.stdout
    # The person can still learn why the pin was passed over (stderr, never the agent's context).
    assert str(broken) in r.stderr and "okl init" in r.stderr, r.stderr


def test_okl_bin_that_cannot_start_falls_through_to_the_pin(repo, tmp_path):
    """Resolution resumes at the next layer, not at PATH: OKL_BIN comes before the pin."""
    broken = _stub(tmp_path / "gone" / "okl", "", shebang="#!/nonexistent/python3")
    pinned = _stub(tmp_path / "pinned" / "okl", 'echo "PINNED BRIEFING $1"')
    _pin(repo, str(pinned))

    r = _prompt(repo, OKL_BIN=str(broken))

    assert r.returncode == 0 and "PINNED BRIEFING check" in r.stdout, (r.returncode, r.stderr)


def test_a_pin_that_cannot_start_with_nothing_to_fall_back_on_blocks_and_names_it(repo, tmp_path):
    """Falling through is not failing open: with no other okl, the prompt is still blocked."""
    broken = _stub(tmp_path / "old venv" / "bin" / "okl", "", shebang="#!/nonexistent/python3.11")
    _pin(repo, str(broken))

    r = _prompt(repo)

    assert r.returncode == 2, r.stdout
    assert str(broken) in r.stderr and "okl init" in r.stderr, r.stderr
    # Claude Code reads the shell's ENOENT phrase as "the hook script is missing" and turns
    # a blocking exit 2 into a warning (see the hook's resolve_okl comment).
    assert "No such file or directory" not in r.stderr, r.stderr


def test_a_launcher_that_ran_slowly_and_exited_127_is_not_run_again(repo, tmp_path):
    """Exit 127 also comes from a launcher that ran (a `docker run` whose image lacks okl).
    Re-running it at each layer took 3 x its time, past Claude Code's 30 s limit, which then
    lets the prompt through unbriefed (review of R21). Only a quick failure falls through."""
    calls = tmp_path / "calls"
    slow = _stub(tmp_path / "bin" / "okl", f'echo run >> "{calls}"; sleep 2; exit 127')
    _pin(repo, str(slow))

    r = _prompt(repo, path=f"{slow.parent}:{BARE}", OKL_BIN=str(slow))

    assert r.returncode == 2, r.stdout
    assert calls.read_text().split() == ["run"]


def test_the_same_failing_command_at_several_layers_runs_once_and_is_named_once(repo, tmp_path):
    """A pin is often the very okl on PATH; failing as one, it was run and named twice."""
    calls = tmp_path / "calls"
    gone = _stub(tmp_path / "bin" / "okl", f'echo run >> "{calls}"; exit 127')
    _pin(repo, str(gone))

    r = _prompt(repo, path=f"{gone.parent}:{BARE}", OKL_BIN=str(gone))

    assert r.returncode == 2, r.stdout
    assert calls.read_text().split() == ["run"]
    assert r.stderr.count("could not start") == 1, r.stderr


def test_the_person_is_told_when_a_broken_pin_was_passed_over(repo, tmp_path):
    """Otherwise the pin stays broken, unseen, and every prompt pays a failed start."""
    broken = _stub(tmp_path / "old venv" / "bin" / "okl", "", shebang="#!/nonexistent/python3.11")
    payload = json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": "B"},
                          "systemMessage": "okl · briefed 1 lesson(s): x"})
    on_path = _stub(tmp_path / "bin" / "okl", f"echo '{payload}'")
    _pin(repo, str(broken))

    r = _prompt(repo, path=f"{on_path.parent}:{BARE}")

    out = _hook_json(r)
    assert out["hookSpecificOutput"]["additionalContext"] == "B"
    assert "okl · briefed 1 lesson(s)" in out["systemMessage"]
    assert str(broken) in out["systemMessage"] and "okl init" in out["systemMessage"]


def test_a_working_pin_runs_nothing_else(repo, tmp_path):
    """The fall-through costs nothing on the path where the pin works."""
    calls = tmp_path / "calls"
    pinned = _stub(tmp_path / "pinned" / "okl", f'echo pinned >> "{calls}"; echo "PINNED $1"')
    on_path = _stub(tmp_path / "bin" / "okl", f'echo path >> "{calls}"; echo "PATH $1"')
    _pin(repo, str(pinned))

    r = _prompt(repo, path=f"{on_path.parent}:{BARE}")

    assert r.returncode == 0 and "PINNED check" in r.stdout
    assert calls.read_text().split() == ["pinned"]


# --- R21: OKL_OFFLINE tells the agent, and the person, that this prompt was not briefed ---

def test_offline_with_no_okl_tells_the_agent_it_was_not_briefed(repo):
    """OKL_OFFLINE=1 let the prompt through with a line on stderr, which the agent never
    sees: it started the task as if a check had found nothing (okl review R21)."""
    _pin(repo, "")

    r = _prompt(repo, OKL_OFFLINE="1")

    assert r.returncode == 0, r.stderr
    out = _hook_json(r)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "NOT BRIEFED" in context and "OKL_OFFLINE" in context
    assert "not a clean check" in context
    assert "not briefed" in out["systemMessage"].lower() and "OKL_OFFLINE" in out["systemMessage"]


def test_offline_after_a_failed_check_passes_the_reason_on(repo, tmp_path):
    """The agent and the person get okl's own reason, not only that no check ran."""
    down = _stub(tmp_path / "bin" / "okl",
                 'echo "OKL UNREACHABLE — refusing to report a clean check." >&2\n'
                 'echo "the okl service at http://okl.internal did not answer" >&2; exit 2')
    _pin(repo, str(down))

    r = _prompt(repo, OKL_OFFLINE="1")

    assert r.returncode == 0, r.stderr
    out = _hook_json(r)
    assert "did not answer" in out["hookSpecificOutput"]["additionalContext"]
    assert "did not answer" in out["systemMessage"]


def test_offline_with_a_pin_that_cannot_start_names_its_fix(repo, tmp_path):
    """The resolver's fix (re-pin with okl init) reaches the person's line too."""
    broken = _stub(tmp_path / "old venv" / "bin" / "okl", "", shebang="#!/nonexistent/python3.11")
    _pin(repo, str(broken))

    r = _prompt(repo, OKL_OFFLINE="1")

    assert r.returncode == 0, r.stderr
    assert "okl init" in _hook_json(r)["systemMessage"]


def test_offline_does_not_replace_a_briefing_that_ran(repo, tmp_path):
    """OKL_OFFLINE only decides what happens when okl cannot brief; it never skips okl."""
    ok = _stub(tmp_path / "bin" / "okl", 'echo "BRIEFING $1"')
    _pin(repo, str(ok))

    r = _prompt(repo, OKL_OFFLINE="1")

    assert r.returncode == 0 and r.stdout.startswith("BRIEFING check"), r.stdout


def test_offline_without_a_working_python_still_reaches_the_agent(repo, tmp_path):
    """The JSON is built by python3; without one, the hook builds it in the shell, so
    neither the agent's notice nor the person's line is lost with it."""
    nopy = _stub(tmp_path / "nopy" / "python3", "exit 1")
    _pin(repo, "")

    r = _prompt(repo, path=f"{nopy.parent}:{BARE}", OKL_OFFLINE="1")

    assert r.returncode == 0, r.stderr
    out = _hook_json(r)
    assert out["hookSpecificOutput"]["additionalContext"].startswith("OKL NOT BRIEFED")
    assert "not briefed" in out["systemMessage"].lower()


def test_offline_strips_control_characters_from_okls_reason(repo, tmp_path):
    """okl's stderr reaches the person's line and the agent's context; a colour code or a
    carriage return in it is noise in both (review of R21)."""
    down = _stub(tmp_path / "bin" / "okl",
                 "printf '\\033[31mOKL UNREACHABLE\\033[0m\\r\\n' >&2; exit 2")
    _pin(repo, str(down))

    r = _prompt(repo, OKL_OFFLINE="1")

    out = _hook_json(r)
    assert "OKL UNREACHABLE" in out["systemMessage"]
    for text in (out["systemMessage"], out["hookSpecificOutput"]["additionalContext"]):
        assert "\x1b" not in text and "\r" not in text, repr(text)


def test_without_offline_an_unreachable_check_still_blocks(repo, tmp_path):
    """R21 makes the escape loud; it does not make it the default (both skeptics)."""
    down = _stub(tmp_path / "bin" / "okl", 'echo "OKL UNREACHABLE" >&2; exit 2')
    _pin(repo, str(down))

    r = _prompt(repo)

    assert r.returncode == 2 and "OKL CHECK DID NOT RUN" in r.stderr, (r.returncode, r.stderr)


# --- a prompt with no text (an image or a file alone) ------------------------------------

def _logging_okl(tmp_path: Path) -> tuple[Path, Path]:
    """An okl on PATH that records every call, so a test can see whether check ran."""
    log = tmp_path / "okl-calls.log"
    okl = _stub(tmp_path / "bin" / "okl", f'echo "$*" >> "{log}"; echo "BRIEFED $1"')
    return okl, log


def _send(repo: Path, okl: Path, payload: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOK)], cwd=repo, text=True, capture_output=True, input=payload,
                          env={"PATH": f"{okl.parent}:{BARE}", "HOME": str(repo.parent), **env})


@pytest.mark.parametrize("payload", [
    {"prompt": ""},
    {"prompt": "   \n "},
    {"hook_event_name": "UserPromptSubmit", "session_id": "s"},   # the key left out
])
def test_a_prompt_with_no_text_briefs_nothing_and_says_so(repo, tmp_path, payload):
    """An image-only prompt was briefed on the last commit's subject: twelve lessons about
    unrelated work. It names no task, so nothing is briefed, and okl is not asked: an okl
    before 0.8.6 answers an empty task with every lesson it has."""
    okl, log = _logging_okl(tmp_path)

    r = _send(repo, okl, json.dumps(payload))

    assert r.returncode == 0, r.stderr
    out = _hook_json(r)
    assert "nothing briefed" in out["hookSpecificOutput"]["additionalContext"]
    assert "nothing to brief on" in out["systemMessage"]
    assert "check" not in (log.read_text() if log.exists() else ""), log.read_text()


def test_okl_task_still_overrides_a_prompt_with_no_text(repo, tmp_path):
    """OKL_TASK is the operator's explicit choice, so it is briefed even with no prompt text."""
    okl, log = _logging_okl(tmp_path)

    r = _send(repo, okl, json.dumps({"prompt": ""}), OKL_TASK="add a refund endpoint")

    assert r.returncode == 0 and "BRIEFED check" in r.stdout, (r.stdout, r.stderr)
    assert "add a refund endpoint" in log.read_text()


def test_a_run_with_no_prompt_event_keeps_the_last_resort_task(repo, tmp_path):
    """Run by hand with nothing on stdin, the hook still briefs on a fallback task."""
    okl, log = _logging_okl(tmp_path)

    r = _send(repo, okl, "")

    assert r.returncode == 0 and "BRIEFED check" in r.stdout, (r.stdout, r.stderr)
    assert "general work" in log.read_text()
