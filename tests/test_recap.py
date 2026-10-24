"""The Stop question names the lessons this session touched (okl review R4, first slice).

It used to ask once, generically, whether the session learned anything. It told the agent
how to update or retire a lesson but never which ones to look at, so in practice the loop
only added: a session made 1 link and narrowed 1 lesson in 107 records (the review). Now
it lists the lessons the session was briefed on and those whose governed files it
changed, so the agent can say which were wrong, out of date or replaced.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from okl import recap
from okl.cli import main
from okl.client import Client

HOOK = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"


def _briefing(*ids: str) -> str:
    lines = ["## OKL briefing — r · task: x", "### ✅ Do this (routed actions)"]
    lines += [f"- **FIX: lesson {i}** [{i}] — when you see: y" for i in ids]
    return "\n".join(lines)


def _attachment(text: str, ts: str = "2026-10-11T10:00:00.000Z") -> str:
    """A UserPromptSubmit hook's context as Claude Code records it in the transcript."""
    return json.dumps({"type": "attachment", "timestamp": ts, "attachment": {
        "type": "hook_additional_context", "hookName": "UserPromptSubmit",
        "hookEvent": "UserPromptSubmit", "content": [text]}})


def _transcript(tmp_path: Path, *lines: str) -> Path:
    t = tmp_path / "session.jsonl"
    t.write_text("\n".join(lines) + "\n")
    return t


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured git repo with a local store and four lessons."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "repo"; (r / ".okl").mkdir(parents=True); (r / "src").mkdir()
    monkeypatch.chdir(r)
    (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    (r / ".gitignore").write_text(".okl/\n")
    (r / "src" / "pay.py").write_text("v1\n"); (r / "src" / "other.py").write_text("v1\n")
    _git(r, "init", "-q"); _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init", "--date", "2026-10-01T00:00:00Z")
    c = Client()
    c.record(id="pay-rule", type="Rule", title="payments go through the ledger", scope="repo",
             files="src/pay.py")
    c.record(id="often", type="Rule", title="a lesson shown often", scope="org")
    c.record(id="once", type="Rule", title="a lesson shown once", scope="org")
    c.record(id="gone", type="Rule", title="a lesson retired", scope="org")
    c.retire("gone", "it was wrong")
    return r


def _git(repo: Path, *args: str) -> None:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin",
           "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z"}
    if "--date" in args:
        i = args.index("--date"); env["GIT_COMMITTER_DATE"] = args[i + 1]
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


# --- reading the transcript -----------------------------------------------------------------

def test_briefed_ids_come_from_the_hooks_context_only(tmp_path):
    """A briefing also appears in tool output (an `okl check` the agent ran); only what the
    prompt hook injected was briefed to the agent as context."""
    tool_output = json.dumps({"type": "user", "toolUseResult": {"stdout": _briefing("noise")},
                              "message": {"content": [{"type": "tool_result",
                                                       "content": _briefing("noise")}]}})
    t = _transcript(tmp_path, _attachment(_briefing("often", "once")),
                    tool_output, "not json at all",
                    _attachment(_briefing("often")))

    counts = recap.briefed_ids(t)

    assert counts == {"often": 2, "once": 1}


def test_a_briefing_saved_to_a_file_is_read_whole(tmp_path):
    """Claude Code keeps a long hook context in a file and puts a 2 KB preview in the
    transcript; the ids past the preview are only in the file."""
    full = tmp_path / "hook-1-additionalContext.txt"
    full.write_text(_briefing("early", "late"))
    preview = (f"<persisted-output>\nOutput too large (10.9KB). Full output saved to: {full}\n\n"
               f"Preview (first 2KB):\n{_briefing('early')}\n...\n</persisted-output>")
    t = _transcript(tmp_path, _attachment(preview))

    assert recap.briefed_ids(t) == {"early": 1, "late": 1}


def test_a_missing_or_unreadable_transcript_is_no_briefings(tmp_path):
    """The transcript is advisory input: no file, no lessons, no error."""
    assert recap.briefed_ids(tmp_path / "nope.jsonl") == {}


def test_the_session_starts_at_the_transcripts_first_timestamp(tmp_path):
    """Unparseable lines are skipped, not fatal."""
    t = _transcript(tmp_path, "garbage", json.dumps({"type": "user", "timestamp": "2026-10-11T09:00:00.000Z"}),
                    _attachment(_briefing("x"), ts="2026-10-11T10:00:00.000Z"))
    assert recap.session_start(t) == "2026-10-11T09:00:00.000Z"


# --- what the session changed ----------------------------------------------------------------

def test_lessons_whose_files_the_session_changed(repo):
    """Uncommitted edits and commits made since the session began count; older commits do not."""
    (repo / "src" / "other.py").write_text("v2\n")
    _git(repo, "commit", "-q", "-am", "before the session", "--date", "2026-10-05T00:00:00Z")
    assert recap.changed_paths(str(repo), since="2026-10-11T09:00:00Z") == set()

    (repo / "src" / "pay.py").write_text("v2\n")
    assert recap.changed_paths(str(repo), since="2026-10-11T09:00:00Z") == {"src/pay.py"}

    _git(repo, "commit", "-q", "-am", "in the session", "--date", "2026-10-11T09:30:00Z")
    assert recap.changed_paths(str(repo), since="2026-10-11T09:00:00Z") == {"src/pay.py"}


# --- the command ------------------------------------------------------------------------------

def test_recap_names_the_lessons_and_the_verbs(repo, capsys):
    """Most-briefed first, live lessons only, files-changed lessons, and the verbs."""
    (repo / "src" / "pay.py").write_text("v2\n")
    t = _transcript(repo.parent, _attachment(_briefing("often", "once", "gone", "not-in-store")),
                    _attachment(_briefing("often")))

    assert main(["recap", "--transcript", str(t)]) == 0
    out = capsys.readouterr().out

    briefed = out[out.index("briefed on"):out.index("governed files")]
    assert briefed.index("[often]") < briefed.index("[once]")      # most often first
    assert "(2×)" in briefed
    assert "[gone]" not in out and "[not-in-store]" not in out     # retired, or no such lesson
    assert "[pay-rule]" in out[out.index("governed files"):]
    for verb in ("okl retire", "okl update", "okl verify", "irrelevant"):
        assert verb in out, verb
    assert "once they agree" in out                                # the person approves


def test_recap_caps_the_briefed_list(repo, capsys):
    """A long session is briefed hundreds of lessons; the question stays short."""
    ids = [f"r{i}" for i in range(8)]
    c = Client()
    for i in ids:
        c.record(id=i, type="Rule", title=f"lesson {i}", scope="org")
    t = _transcript(repo.parent, _attachment(_briefing(*ids)))

    main(["recap", "--transcript", str(t), "--limit", "3"])

    assert capsys.readouterr().out.count("\n  [") == 3


def test_recap_caps_the_changed_list_and_points_to_drift(repo, capsys):
    """A session that ran for days changes most of a repo; the question stays short."""
    c = Client()
    for i in range(4):
        (repo / "src" / f"m{i}.py").write_text("v1\n")
        c.record(id=f"m{i}", type="Rule", title=f"module {i}", scope="repo", files=f"src/m{i}.py")
    t = _transcript(repo.parent, json.dumps({"type": "user", "timestamp": "2026-10-11T09:00:00Z"}))

    main(["recap", "--transcript", str(t), "--limit", "2"])
    out = capsys.readouterr().out

    assert out.count("\n  [m") == 2 and "and 2 more" in out and "okl drift" in out, out


def test_recap_prints_nothing_when_the_session_touched_nothing(repo, capsys):
    """Nothing to add is no text, so the hook's question stands alone."""
    t = _transcript(repo.parent, json.dumps({"type": "user", "timestamp": "2026-10-11T09:00:00Z"}))

    assert main(["recap", "--transcript", str(t)]) == 0
    assert capsys.readouterr().out == ""


# --- the Stop hook ----------------------------------------------------------------------------

def _stop(repo: Path, okl_body: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "bin" / "okl"
    stub.parent.mkdir(exist_ok=True)
    stub.write_text(f"#!/bin/sh\n{okl_body}\n"); stub.chmod(0o755)
    t = _transcript(tmp_path, json.dumps({"type": "user", "timestamp": "2026-10-11T09:00:00Z"}))
    (repo / "dirty.txt").write_text("a change, so the hook has a reason to ask")
    return subprocess.run(["bash", str(HOOK)], cwd=repo, text=True, capture_output=True,
                          input=json.dumps({"session_id": "s1", "stop_hook_active": False,
                                            "transcript_path": str(t)}),
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
                               "OKL_BIN": str(stub)})


def test_the_stop_hook_adds_the_recap(repo, tmp_path):
    """The hook appends what okl recap prints to its question."""
    r = _stop(repo, '[ "$1" = recap ] && echo "RECAP for $3"', tmp_path)

    assert r.returncode == 2, r.stderr
    assert "ENCODING LOOP" in r.stderr and "RECAP for " in r.stderr, r.stderr


def test_the_stop_hook_asks_as_before_with_an_okl_that_has_no_recap(repo, tmp_path):
    """The plugin updates from main and the CLI only when upgraded (hook-cli-version-skew)."""
    r = _stop(repo, 'echo "okl: error: argument cmd: invalid choice: \'recap\'" >&2; exit 2', tmp_path)

    assert r.returncode == 2 and "ENCODING LOOP" in r.stderr
    assert "invalid choice" not in r.stderr, r.stderr


# --- the session report (#279) --------------------------------------------------------------

def test_the_window_reads_iso_relative_the_transcript_or_a_day(tmp_path):
    """--since takes ISO 8601 or a span back from now; without it the transcript's start;
    without that, a day; an unreadable --since is an error the command can name."""
    now = recap._iso_ms("2026-10-24T12:00:00Z")
    assert recap.window_start("2026-10-24T10:00Z", None, now) == now - 2 * 3_600_000
    assert recap.window_start("90m", None, now) == now - 90 * 60_000
    assert recap.window_start("2d", None, now) == now - 2 * 86_400_000
    t = _transcript(tmp_path, json.dumps({"timestamp": "2026-10-24T11:00:00.000Z"}))
    assert recap.window_start(None, str(t), now) == now - 3_600_000
    assert recap.window_start(None, None, now) == now - 86_400_000
    with pytest.raises(ValueError):
        recap.window_start("yesterday-ish", None, now)


def test_the_report_counts_what_happened_in_the_window(repo):
    """Briefings, recorded and retired lessons, check runs (failures named), changed files
    and current drift all come from the store's logs and git, inside the window only."""
    c = Client()
    c.check("payments go through the ledger")
    c.check("payments go through the ledger")
    store = c._local_store()
    store.log_check("often", True, "pytest -q", "exit 0")
    store.log_check("once", False, "ruff check .", "exit 1")
    (repo / "src" / "pay.py").write_text("v2\n")          # uncommitted: the session changed it
    now = recap._iso_ms("2100-01-01T00:00:00Z")
    r = recap.report(store, "r", str(repo), since_ms=0, now_ms=now)
    assert r["briefings"] == 2 and r["most_shown"][0]["id"] == "pay-rule" and r["most_shown"][0]["times"] == 2
    assert {x["id"] for x in r["recorded"]} == {"pay-rule", "often", "once", "gone"}
    assert [x["id"] for x in r["retired"]] == ["gone"] and r["retired"][0]["reason"] == "it was wrong"
    assert r["checks"]["runs"] == 2 and r["checks"]["passed"] == 1
    assert [x["id"] for x in r["checks"]["failed"]] == ["once"]
    assert [x["id"] for x in r["changed"]] == ["pay-rule"]
    assert [x["id"] for x in r["stale_now"]] == ["pay-rule"]          # never verified, and governs a file
    later = recap.report(store, "r", str(repo), since_ms=now - 1, now_ms=now)
    assert later["briefings"] == 0 and later["recorded"] == [] and later["retired"] == []
    assert later["checks"]["runs"] == 0


def test_recap_report_prints_markdown_or_json(repo, capsys):
    """The command prints the sections a person reads, says what it does not cover yet, and
    gives the same data as JSON; an unreadable --since exits 2 with the forms it accepts."""
    Client().check("payments go through the ledger")
    assert main(["recap", "--report", "--since", "1h"]) == 0
    out = capsys.readouterr().out
    for heading in ("okl session report", "**Briefings:** 1 prompts", "**Lessons recorded:**",
                    "**Lessons retired:** 1", "**Checks run:**", "**Code:**", "**Still open:**",
                    "Not covered yet"):
        assert heading in out, heading
    assert main(["recap", "--report", "--since", "1h", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["repo"] == "r" and data["briefings"] == 1
    assert main(["recap", "--report", "--since", "whenever"]) == 2
    assert "90m, 6h, 2d" in capsys.readouterr().err
