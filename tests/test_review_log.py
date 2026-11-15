"""The review log: what each session's review after writing did, read from its transcript (#464).

0.17.0 turned the review on by default as a decision, not a measured result, and named real-use
evidence that it almost never acts as what would reverse it. Nothing collected that evidence. The
agent runs the review and okl calls no model, so only the session's transcript sees it: that it ran,
the sub-agents it started, the lessons each opened, what each edited, the tests run, the tokens.
The Stop hook now reads the transcript at a later stop and keeps one row per session; `okl recap
--reviews` reads the rows back. Every transcript here is synthetic, written in the shape Claude
Code saves: one line per content block, the main transcript beside a folder of sub-agent
transcripts with their meta files.
"""
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from okl import core, recap, reviewlog
from okl import store as store_mod
from okl.cli import main
from okl.client import Client
from okl.store import Store

T0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=UTC)
REVIEW_OUT = ("## OKL review after writing — r · 4 file(s) changed since main (merge base abc1234), "
              "committed or not\n\nThis review lists 12 lesson(s) in about 1 KB. Read all of it before "
              "you pick.\n")
NOTE = ("REVIEW AFTER WRITING (on in this repo): before you answer the question below, check the code "
        "this session wrote against the lessons. Run `okl check --change` and follow its steps.")


# --- building transcripts --------------------------------------------------------------------------

def _at(sec: int) -> str:
    return (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _user(sec: int, text: str) -> str:
    return json.dumps({"type": "user", "timestamp": _at(sec), "message": {"role": "user", "content": text}})


def _feedback(sec: int, note: bool = True) -> str:
    """The Stop hook's blocking feedback, as Claude Code writes it into the transcript."""
    text = ('Stop hook feedback:\n["$CLAUDE_PROJECT_DIR"/.claude/hooks/stop-okl-encode.sh]: '
            + (NOTE + "\n" if note else "") + "ENCODING LOOP — before this session ends: did it surface a lesson?")
    return json.dumps({"type": "user", "isMeta": True, "timestamp": _at(sec),
                       "message": {"role": "user", "content": text}})


def _call(tid: str, name: str, **inp) -> dict:
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _say(text: str) -> dict:
    return {"type": "text", "text": text}


def _turn(sec: int, mid: str, *blocks: dict, usage: tuple[int, int, int, int] = (1, 1, 1, 1),
          model: str = "claude-opus-5-5") -> str:
    """One assistant message: Claude Code writes a line per content block, each with the whole
    message's usage, so a message with two blocks must still be counted once."""
    u = dict(zip(("input_tokens", "output_tokens", "cache_creation_input_tokens",
                  "cache_read_input_tokens"), usage, strict=True))
    return "\n".join(json.dumps({"type": "assistant", "timestamp": _at(sec), "message": {
        "id": mid, "role": "assistant", "model": model, "content": [b], "usage": u}}) for b in blocks)


def _result(sec: int, tid: str, text: str, *, error: bool = False, **tool_use_result) -> str:
    line = {"type": "user", "timestamp": _at(sec), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": error}]}}
    if tool_use_result:
        line["toolUseResult"] = tool_use_result
    return json.dumps(line)


def _write(tmp_path: Path, main_lines: list[str], agents: dict | None = None, session: str = "sess-1") -> Path:
    """`<projects>/<session>.jsonl`, and for each agent id (meta or None, transcript lines or None)
    the files Claude Code keeps under `<session>/subagents/`."""
    proj = tmp_path / "projects"
    proj.mkdir(exist_ok=True)
    t = proj / f"{session}.jsonl"
    t.write_text("\n".join(main_lines) + "\n")
    for aid, (meta, lines) in (agents or {}).items():
        sub = proj / session / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        if lines is not None:
            (sub / f"agent-{aid}.jsonl").write_text("\n".join(lines) + "\n")
        if meta is not None:
            (sub / f"agent-{aid}.meta.json").write_text(json.dumps(meta))
    return t


def _shown(lesson: str) -> str:
    """A lesson's text as `okl show` prints it, pasted into a sub-agent's prompt."""
    return f"[{lesson}] Rule · org · created 2026-11-01 10:00Z\n  a title\n  fix: do the thing"


def _two_agents(tmp_path: Path, root: str = "/work/repo") -> Path:
    """A review with two sub-agents: `aaa` opens les-a, edits a file and runs a test; `bbb` opens
    les-b and changes nothing."""
    main_lines = [
        _user(0, "fix the bug"),
        _feedback(100),
        _turn(110, "m1", _call("tu-rev", "Bash", command="okl check --change"), usage=(10, 20, 30, 40)),
        _result(112, "tu-rev", REVIEW_OUT),
        # two blocks, one message: its usage (10 tokens) is on both lines and counts once
        _turn(120, "m2", _say("starting the first"),
              _call("tu-a1", "Agent", description="SECRET DESCRIPTION", prompt=_shown("les-a"),
                    subagent_type="general-purpose"), usage=(1, 2, 3, 4)),
        _result(121, "tu-a1", "launched", agentId="aaa", status="async_launched"),
        _turn(122, "m3", _call("tu-a2", "Agent", description="second", prompt="look at les-b"),
              usage=(1, 2, 3, 4)),
        _result(123, "tu-a2", "launched", agentId="bbb", status="async_launched"),
        _turn(300, "m4", _say("done"), usage=(5, 5, 5, 5)),
    ]
    agent_a = [
        _turn(130, "a1", _call("x1", "Bash", command="okl show les-a"), usage=(1, 1, 1, 1)),
        _result(131, "x1", "[les-a] Rule · org"),
        _turn(140, "a2", _call("e1", "Edit", file_path=f"{root}/src/x.py", new_string="SECRET CODE",
                               old_string="OLDTEXT"), usage=(1, 1, 1, 1)),
        _result(141, "e1", "edited"),
        _turn(150, "a3", _call("t1", "Bash", command="pytest tests/test_x.py -q 2>&1 | tail -3"),
              usage=(1, 1, 1, 1)),
        _result(151, "t1", "3 passed in 0.1s"),
        _turn(160, "a4", _say("fixed"), usage=(1, 1, 1, 1)),
    ]
    agent_b = [
        _turn(170, "b1", _call("y1", "Bash", command="okl show les-b"), usage=(2, 2, 2, 2), model="claude-sonnet-4-6"),
        _result(171, "y1", "[les-b] Rule · org"),
        _turn(250, "b2", _say("no bearing"), usage=(2, 2, 2, 2), model="claude-sonnet-4-6"),
    ]
    return _write(tmp_path, main_lines, {
        "aaa": ({"toolUseId": "tu-a1", "model": "opus", "pickedEffortModel": "opus",
                 "description": "SECRET DESCRIPTION"}, agent_a),
        "bbb": ({"toolUseId": "tu-a2", "model": "sonnet"}, agent_b)})


# --- what the transcript says --------------------------------------------------------------------

def test_a_review_with_two_subagents_one_that_edits_and_one_that_does_not(tmp_path):
    """Asked, run, the files and lessons its own output named, then per sub-agent: its model from the
    meta file, the lessons it opened, whether and what it edited, the tests it ran with their outcome."""
    t = _two_agents(tmp_path)

    r = reviewlog.read_review(t, repo_dir="/work/repo", known_ids={"les-a", "les-b"})

    assert (r.session, r.readable, r.asked, r.ran, r.loggable) == ("sess-1", True, True, True, True)
    assert (r.files_changed, r.lessons_listed) == (4, 12)
    a, b = r.checks
    assert (a["agent"], a["model"], a["lessons"], a["read"]) == ("aaa", "opus", ["les-a"], True)
    assert (a["edited"], a["edited_files"]) == (True, ["src/x.py"])          # relative to the repository
    assert a["tests"] == [{"runner": "pytest", "targets": ["tests/test_x.py"], "outcome": "passed"}]
    assert (b["agent"], b["model"], b["lessons"], b["edited"], b["edited_files"], b["tests"]) == (
        "bbb", "sonnet", ["les-b"], False, [], [])
    # tokens: the main transcript's messages from the first call on (100 + 10 + 10 + 20, the two-block
    # message once) and every sub-agent's (4 messages of 4, 2 of 8); the time runs to the last event
    assert r.tokens == 140 + 16 + 16
    assert r.duration_s == 300 - 110


def test_a_row_holds_no_code_and_no_session_text(tmp_path):
    """Ids, paths, counts, model names and booleans: not the edit's text, not the sub-agent's description."""
    r = reviewlog.read_review(_two_agents(tmp_path), repo_dir="/work/repo")

    stored = json.dumps([r.checks, r.session, r.files_changed])
    assert not any(w in stored for w in ("SECRET", "OLDTEXT", "launched", "fixed"))


def test_the_marker_is_the_start_of_the_note_the_hook_prints():
    """The parser finds the request by the words okl's note starts with. If the note changes, this fails
    rather than every session quietly reading as never asked."""
    assert core.REVIEW_NOTE.startswith(reviewlog.NOTE.decode())


def test_a_review_with_no_subagents(tmp_path):
    """The agent that cannot start a sub-agent checks the lessons itself: a review that ran with no
    checks, and its own tokens and time."""
    t = _write(tmp_path, [
        _user(0, "x"), _feedback(10),
        _turn(20, "m1", _call("tu-rev", "Bash", command="cd /work/repo && okl check --change main | head -80"),
              usage=(1, 1, 1, 1)),
        _result(21, "tu-rev", REVIEW_OUT),
        _turn(90, "m2", _say("checked them myself"), usage=(2, 2, 2, 2))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.checks) == (True, True, [])
    assert (r.files_changed, r.lessons_listed, r.tokens, r.duration_s) == (4, 12, 4 + 8, 70)


def test_the_note_was_shown_but_no_review_ran(tmp_path):
    """The review asked for and skipped: a row that says so, with no tokens or time to claim."""
    t = _write(tmp_path, [_user(0, "x"), _feedback(10),
                          _turn(20, "m1", _say("nothing worth recording"), usage=(9, 9, 9, 9))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.loggable) == (True, False, True)
    assert (r.files_changed, r.lessons_listed, r.tokens, r.duration_s, r.checks) == (None, None, None, None, [])


def test_no_note_and_no_review_is_not_logged(tmp_path):
    """A session the hook never asked, with no review run, says nothing about the review."""
    t = _write(tmp_path, [_user(0, "x"), _feedback(10, note=False), _turn(20, "m1", _say("ok"))])

    r = reviewlog.read_review(t)

    assert (r.readable, r.asked, r.ran, r.loggable) == (True, False, False, False)


def test_the_words_in_a_tool_result_are_not_the_note_and_the_hooks_own_call_is_not_the_review(tmp_path):
    """okl's own source and docs hold the note's words and `okl check --change`: a grep that prints
    them, or the hook-format call, must not read as a request or a review."""
    t = _write(tmp_path, [
        _user(0, "x"),
        _turn(5, "m1", _call("g", "Bash", command="grep -rn 'REVIEW AFTER WRITING' src")),
        _result(6, "g", f"src/okl/core.py:1598:REVIEW_NOTE = {NOTE}"),
        _turn(7, "m2", _call("h", "Bash", command="okl check --change --format hook"), usage=(1, 1, 1, 1)),
        _result(8, "h", NOTE)])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran) == (False, False)


def test_a_subagent_whose_meta_file_is_missing_is_found_by_the_agent_id_the_call_returned(tmp_path):
    """The meta file ties a sub-agent to its call by tool id; without it the call's own result names
    the agent, and the model falls back to the sub-agent's transcript."""
    main_lines = [
        _user(0, "x"), _feedback(10),
        _turn(20, "m1", _call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        _result(21, "tu-rev", REVIEW_OUT),
        _turn(30, "m2", _call("tu-a", "Agent", prompt="check it"), usage=(1, 1, 1, 1)),
        _result(31, "tu-a", "launched", agentId="ccc")]
    agent = [_turn(40, "c1", _call("x", "Bash", command="okl show les-c"), usage=(1, 1, 1, 1),
                   model="claude-sonnet-4-6"), _result(41, "x", "text")]
    t = _write(tmp_path, main_lines, {"ccc": (None, agent)})

    (c,) = reviewlog.read_review(t).checks

    assert (c["agent"], c["model"], c["lessons"], c["read"]) == ("ccc", "claude-sonnet-4-6", ["les-c"], True)


def test_a_subagent_with_neither_meta_nor_transcript_is_recorded_as_unread(tmp_path):
    """What cannot be read is left out, not guessed: no edit is claimed either way, and the lesson
    its prompt carried (as `okl show` prints it) is still named."""
    t = _write(tmp_path, [
        _user(0, "x"),
        _turn(20, "m1", _call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        _result(21, "tu-rev", REVIEW_OUT),
        _turn(30, "m2", _call("tu-a", "Agent", prompt=_shown("les-z"), model="haiku"), usage=(1, 1, 1, 1)),
        _result(31, "tu-a", "plain text, no agent id")])

    (c,) = reviewlog.read_review(t).checks

    assert (c["agent"], c["read"], c["edited"], c["lessons"], c["tokens"], c["model"]) == (
        None, False, False, ["les-z"], None, "haiku")


def test_a_meta_file_whose_transcript_is_missing_is_unread(tmp_path):
    """The meta file names the agent and its model, but with no transcript nothing else is known."""
    t = _write(tmp_path, [
        _user(0, "x"),
        _turn(20, "m1", _call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        _result(21, "tu-rev", REVIEW_OUT),
        _turn(30, "m2", _call("tu-a", "Task", prompt=_shown("les-a")), usage=(1, 1, 1, 1))],
        {"ddd": ({"toolUseId": "tu-a", "model": "opus"}, None)})

    (c,) = reviewlog.read_review(t).checks

    assert (c["agent"], c["read"], c["model"], c["lessons"]) == ("ddd", False, "opus", ["les-a"])


@pytest.mark.parametrize("make", ["missing", "directory", "garbage", "empty"])
def test_an_unreadable_transcript_never_raises(tmp_path, make):
    """A missing file, a folder, binary noise and an empty file each give a reading and no error."""
    t = tmp_path / "s.jsonl"
    if make == "directory":
        t.mkdir()
    elif make == "garbage":
        t.write_bytes(b"\xff\xfe not json \x00\n{\"truncated\": \n[1, 2\n" + b"\x80" * 64)
    elif make == "empty":
        t.write_text("")

    r = reviewlog.read_review(t)

    assert r.loggable is False and r.checks == [] and r.ran is False
    assert r.readable is (make in ("garbage", "empty"))


def test_an_edit_the_tool_refused_is_not_an_edit(tmp_path):
    """A call whose result is an error changed nothing; one the transcript has no result for is counted."""
    t = _write(tmp_path, [
        _user(0, "x"),
        _turn(20, "m1", _call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        _result(21, "tu-rev", REVIEW_OUT),
        _turn(30, "m2", _call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
        _result(31, "tu-a", "launched", agentId="eee")], {"eee": (None, [
            _turn(40, "e1", _call("x1", "Edit", file_path="/r/a.py"), usage=(1, 1, 1, 1)),
            _result(41, "x1", "String to replace not found", error=True),
            _turn(42, "e2", _call("x2", "mcp__okl__okl_get", id="les-a"), usage=(1, 1, 1, 1))])})

    (c,) = reviewlog.read_review(t).checks

    assert c["edited"] is False and c["lessons"] == ["les-a"]     # the MCP tool's id counts as opened


def test_only_lessons_the_store_has_reach_a_row(tmp_path):
    """A command line is session text: an id that is no lesson here, or no id at all, is dropped."""
    t = _write(tmp_path, [
        _user(0, "x"),
        _turn(20, "m1", _call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        _result(21, "tu-rev", REVIEW_OUT),
        _turn(30, "m2", _call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
        _result(31, "tu-a", "launched", agentId="fff")], {"fff": (None, [
            _turn(40, "f1", _call("x1", "Bash", command="okl show les-a; okl show 'rm -rf /'; okl show nope"),
                  usage=(1, 1, 1, 1))])})

    (c,) = reviewlog.read_review(t, known_ids={"les-a"}).checks
    (open_c,) = reviewlog.read_review(t).checks

    assert c["lessons"] == ["les-a"]
    assert open_c["lessons"] == ["les-a", "rm", "nope"]     # without the store, only the id's shape is held


def test_the_commands_the_parser_recognizes():
    """The review's command, the lessons `okl show` names, and a test run: a mention is not a run."""
    assert reviewlog.is_review_command("okl check --change")
    assert reviewlog.is_review_command("python3 -m okl check --format json --change origin/main")
    assert reviewlog.is_review_command('"$OKL" check --change 2>&1 | head')
    assert not reviewlog.is_review_command("okl check --change --format hook")
    assert not reviewlog.is_review_command("okl check --task 'add a login page'")
    assert not reviewlog.is_review_command("git diff --change")
    assert reviewlog.show_ids("okl show a; okl show --format json b && okl show c --format json") == ["a", "b", "c"]
    assert reviewlog.parse_test_run("FOO=1 .venv/bin/pytest -q tests/a.py::test_x tests/sub/") == (
        "pytest", ["tests/a.py", "tests/sub/"])
    assert reviewlog.parse_test_run("cd app && npm run test -- src/x.test.ts")[0] == "npm run test"
    assert reviewlog.parse_test_run("grep -rn pytest docs/") is None
    assert reviewlog.parse_test_run("ruff check .") is None
    assert reviewlog.parse_test_outcome(False, "5 passed in 1s") == "passed"
    assert reviewlog.parse_test_outcome(False, "5 passed, 1 failed") == "failed"
    assert reviewlog.parse_test_outcome(True, "Exit code 1") == "failed"
    assert reviewlog.parse_test_outcome(False, "collected nothing") == "unknown"


# --- the store ---------------------------------------------------------------------------------

def test_a_session_logged_again_replaces_its_row(tmp_path):
    """One row per (session, repo): the transcript grew since the last stop, so the last reading wins."""
    s = Store(f"sqlite:///{tmp_path / 'okl.db'}")
    check = {"agent": "a", "model": "opus", "lessons": ["l1"], "edited": True, "edited_files": ["x.py"],
             "tests": [], "tokens": 5, "read": True}
    s.log_review("s1", "r", asked=True, ran=False)
    s.log_review("s1", "r", asked=True, ran=True, files_changed=3, lessons_listed=9, tokens=100,
                 duration_s=40, checks=[check])
    s.log_review("s1", "other", asked=False, ran=True)
    s.log_review("s2", "r", asked=True, ran=False)

    mine = s.reviews("r")

    assert [(x.session_id, x.asked, x.ran) for x in mine] == [("s1", True, True), ("s2", True, False)]
    first = mine[0]
    assert (first.files_changed, first.lessons_listed, first.tokens, first.duration_s) == (3, 9, 100, 40)
    assert first.checks == (check,) and isinstance(first.asked, bool)
    assert (mine[1].files_changed, mine[1].tokens, mine[1].checks) == (None, None, ())
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


# --- the command -----------------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repository with a local store and two lessons."""
    r = tmp_path / "repo"; (r / ".okl").mkdir(parents=True)
    (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.chdir(r)
    c = Client()
    c.record(id="les-a", type="Rule", title="the first lesson", scope="org")
    c.record(id="les-b", type="Rule", title="the second lesson", scope="org")
    return r


def _rows(repo: Path):
    return Client()._local_store().reviews("r")


def test_log_review_writes_the_row_and_exits_0(repo, tmp_path, capsys):
    """The command reads the transcript, writes the row with paths relative to the repository, and a
    later stop of the same session replaces it rather than adding a second."""
    t = _two_agents(tmp_path, root=str(repo))

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0

    assert "logged session sess-1" in capsys.readouterr().out
    (row,) = _rows(repo)
    assert (row.session_id, row.asked, row.ran, row.files_changed, row.lessons_listed) == ("sess-1", True, True, 4, 12)
    assert [c["lessons"] for c in row.checks] == [["les-a"], ["les-b"]]
    assert row.checks[0]["edited_files"] == ["src/x.py"]       # relative to the repository okl runs in
    # a later stop of the same session replaces the row
    assert main(["recap", "--transcript", str(t), "--log-review"]) == 0
    assert len(_rows(repo)) == 1


def test_log_review_exits_0_and_writes_nothing_when_there_was_no_review(repo, tmp_path, capsys):
    """A session with no review, and a transcript that cannot be read, are both exit 0 and no row."""
    quiet = _write(tmp_path, [_user(0, "x"), _turn(5, "m1", _say("ok"))], session="quiet")

    assert main(["recap", "--transcript", str(quiet), "--log-review"]) == 0
    assert "nothing logged" in capsys.readouterr().out
    assert main(["recap", "--transcript", str(tmp_path / "gone.jsonl"), "--log-review"]) == 0
    assert "cannot read" in capsys.readouterr().err
    assert _rows(repo) == []


def test_log_review_exits_2_only_when_the_store_cannot_be_written(repo, tmp_path, monkeypatch, capsys):
    """Exit 2 is for a store that refuses the write, and for no transcript named; nothing else."""
    t = _two_agents(tmp_path)

    def refuse(self, run):
        raise sqlite3.OperationalError("attempt to write a readonly database")
    monkeypatch.setattr(store_mod._SQLiteBackend, "log_review", refuse)

    assert main(["recap", "--transcript", str(t), "--log-review"]) == 2
    err = capsys.readouterr().err
    assert "review log cannot be used" in err and "readonly" in err
    assert main(["recap", "--log-review"]) == 2     # no transcript named: a usage refusal, nothing written
    assert "needs --transcript" in capsys.readouterr().err


def _check(lessons, *, read=True, edited=False):
    return {"agent": "a", "model": "opus", "lessons": lessons, "read": read, "edited": edited,
            "edited_files": [], "tests": [], "tokens": 1}


def _fill(store):
    """Four sessions: two reviews with checks, one asked and skipped, one run without being asked."""
    store.log_review("s1", "r", asked=True, ran=True, files_changed=3, lessons_listed=10, tokens=1000,
                     duration_s=60, checks=[_check(["les-a"], edited=True), _check(["les-b"])])
    store.log_review("s2", "r", asked=True, ran=True, files_changed=2, lessons_listed=10, tokens=3000,
                     duration_s=120, checks=[_check(["les-a"]), _check(["les-c"], read=False),
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
    assert "**Lessons checked per review:** median 2, mean 1.3, most 2; 1 reviews started no sub-agent." in out
    assert "**Checks:** 4 (a sub-agent given a lesson); 1 could not be read, and of the 3 that could, 1 (33%)" in out
    assert "Tokens: median 2,000, mean 2,000, largest 3,000." in out and "Duration: median 90 s" in out
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
