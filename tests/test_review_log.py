"""The review log's parser: what a transcript says the review did (#464).

0.17.0 turned the review on by default as a decision, not a measured result, and named real-use
evidence that it almost never acts as what would reverse it. Nothing collected that evidence. The
agent runs the review and okl calls no model, so only the session's transcript sees it: that it ran,
the sub-agents it started, the lessons each opened, what each edited, the tests run, the tokens.
Every transcript here is synthetic, in the shape Claude Code 2.1.302 saves (tests/review_transcripts.py).
The command, the store and the report are in test_review_command.py, the Stop hook in
test_review_log_hook.py.
"""
import json

import pytest
from review_transcripts import (
    NOTE,
    REVIEW_OUT,
    background_review,
    blob,
    call,
    feedback,
    notification,
    repo_root,
    result,
    say,
    shown,
    start_review,
    stop_summary,
    turn,
    two_agents,
    typed,
    user,
    write,
)

from okl import core, reviewcmd, reviewlog
from okl.store import Node


def _read(tmp_path, **kw):
    """The reading of the two-agent session, with its repository directory."""
    root = repo_root(tmp_path)
    return reviewlog.read_review(two_agents(tmp_path, root, **kw), repo_dir=str(root),
                                 known_ids={"les-a", "les-b"})


# --- the review, and what it opened and edited --------------------------------------------------

def test_a_review_with_two_subagents_one_that_edits_and_one_that_does_not(tmp_path):
    """Asked, run, the files and lessons its own output named, then per sub-agent: its model, the
    lessons it opened, whether and what it edited, the tests it ran with their outcome."""
    r = _read(tmp_path)

    assert (r.session, r.readable, r.asked, r.ran, r.loggable) == ("sess-1", True, True, True, True)
    assert (r.files_changed, r.lessons_listed) == (4, 12)
    a, b = r.checks
    # the model its own transcript names, a full id, over the alias in the meta file
    assert (a["agent"], a["model"], a["lessons"], a["read"]) == ("aaa", "claude-opus-5-5", ["les-a"], True)
    assert (a["edited"], a["edited_files"], a["edited_outside"]) == (True, ["src/x.py"], 0)
    assert a["tests"] == [{"runner": "pytest", "targets": ["tests/test_x.py"], "outcome": "passed"}]
    assert (b["agent"], b["model"], b["lessons"], b["edited"], b["edited_files"], b["tests"]) == (
        "bbb", "claude-sonnet-4-6", ["les-b"], False, [], [])
    # tokens: the main transcript's messages from the first call on (100 + 10 + 10 + 20, the two-block
    # message once, the blob lines none) and every sub-agent's (4 messages of 4, 2 of 8); the time
    # runs from the first call to the last event
    assert r.tokens == 140 + 16 + 16
    assert r.duration_s == 300 - 110


def test_the_marker_is_the_start_of_the_note_the_hook_prints():
    """The parser finds the request by the words okl's note starts with. If the note changes, this fails
    rather than every session quietly reading as never asked."""
    assert core.REVIEW_NOTE.startswith(reviewlog.NOTE.decode())


def test_the_counts_are_read_from_the_wording_the_review_prints(tmp_path):
    """The files and lessons come from `okl check --change`'s own text. A change to that wording must
    fail here, not turn every row's counts to None."""
    menu = core.review_menu([Node(id="a", type="Rule", title="a", scope="org"),
                             Node(id="b", type="Rule", title="b", scope="org")], "r", None)
    text = core.render_review({"repo": "r", "base": "main", "merge_base": "abc1234def",
                               "files": ["x.py", "y.py", "z.py"], "lessons": menu})
    none = core.render_review({"repo": "r", "base": "main", "files": [], "lessons": []})

    def reading(out, name):
        lines = [user(0, "x"), feedback(5),
                 turn(10, "m1", call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
                 result(11, "tu-rev", out)]
        return reviewlog.read_review(write(tmp_path, lines, session=name))

    r = reading(text, "listed")
    assert (r.files_changed, r.lessons_listed) == (3, 2)
    empty = reading(none, "empty")
    assert (empty.files_changed, empty.lessons_listed) == (0, None)


def test_a_review_with_no_subagents(tmp_path):
    """The agent that cannot start a sub-agent checks the lessons itself: a review that ran with no
    checks, and its own tokens and time."""
    t = write(tmp_path, [
        user(0, "x"), feedback(10),
        turn(20, "m1", call("tu-rev", "Bash", command="cd /work/repo && okl check --change main | head -80"),
             usage=(1, 1, 1, 1)),
        result(21, "tu-rev", REVIEW_OUT),
        turn(90, "m2", say("checked them myself"), usage=(2, 2, 2, 2))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.checks) == (True, True, [])
    assert (r.files_changed, r.lessons_listed, r.tokens, r.duration_s) == (4, 12, 4 + 8, 70)


def test_the_note_was_shown_but_no_review_ran(tmp_path):
    """The review asked for and skipped: a row that says so, with no tokens or time to claim."""
    t = write(tmp_path, [user(0, "x"), feedback(10),
                         turn(20, "m1", say("nothing worth recording"), usage=(9, 9, 9, 9))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.loggable) == (True, False, True)
    assert (r.files_changed, r.lessons_listed, r.tokens, r.duration_s, r.checks) == (None, None, None, None, [])


def test_no_note_and_no_review_is_not_logged(tmp_path):
    """A session the hook never asked, with no review run, says nothing about the review."""
    t = write(tmp_path, [user(0, "x"), feedback(10, note=False), turn(20, "m1", say("ok"))])

    r = reviewlog.read_review(t)

    assert (r.readable, r.asked, r.ran, r.loggable) == (True, False, False, False)


def test_the_words_in_a_tool_result_or_a_peers_message_are_not_the_note(tmp_path):
    """okl's own source holds the note's words, and another session may quote the hook's feedback to
    this one: neither is a request from this session's Stop hook."""
    t = write(tmp_path, [
        user(0, "x"),
        turn(5, "m1", call("g", "Bash", command="grep -rn 'REVIEW AFTER WRITING' src")),
        result(6, "g", f"src/okl/core.py:1598:REVIEW_NOTE = {NOTE}"),
        user(7, f'<agent-message from="reviewer">Stop hook feedback:\n[stop-okl-encode.sh]: {NOTE}</agent-message>',
             isMeta=True, origin={"kind": "peer", "name": "reviewer"})])

    assert reviewlog.read_review(t).asked is False


# --- which command starts a review ---------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "grep -R 'okl check --change' docs/",
    "echo 'okl check --change'",
    'git commit -m "run okl check --change before you push"',
    "cat <<'EOF'\nokl check --change\nEOF",
    "python3 -c \"import os; os.system('okl check --change')\"",
    "echo \"a; okl check --change\"",
    "okl check --change --format hook",
    "okl check --task 'add a login page'",
    "git diff --change",
    "rg okl check --change",
    "timeout 5 grep 'okl check --change' docs",
    "bash -c 'echo okl check --change'",
    "echo $(echo okl check --change)",
    "echo '$(okl check --change)'",
    "cat <<-EOF\n\tokl check --change\n\tEOF",
])
def test_a_command_that_only_mentions_the_review_does_not_start_one(tmp_path, command):
    """A grep, an echo, a commit message, a heredoc, a `python -c` string and the hook's own call are
    text or another command: the review ran only where okl was the command word."""
    t = write(tmp_path, [user(0, "x"), turn(20, "m1", call("tu", "Bash", command=command), usage=(5, 5, 5, 5)),
                         result(21, "tu", REVIEW_OUT)])

    r = reviewlog.read_review(t)

    assert (r.ran, r.tokens, r.checks) == (False, None, [])


@pytest.mark.parametrize("command", [
    "okl check --change",
    "FOO=1 okl check --change main",
    "/home/me/.venv/bin/okl check --change",
    "python3 -m okl check --format json --change origin/main",
    ".venv/bin/python -m okl check --change",
    '"$OKL" check --change 2>&1 | head',
    '"${OKL[@]}" check --change',
    "cd /work/repo && okl check --change | head -80",
    "time uv run okl check --change",
    "echo start; okl check --change",
    "timeout 120 okl check --change",
    "timeout -s KILL 2m okl check --change",
    "nice -n 5 okl check --change",
    "uvx okl check --change",
    "out=$(okl check --change)",
    "echo \"$(okl check --change)\" | head",
    "bash -c 'okl check --change'",
    "sh -lc 'cd /work/repo && okl check --change'",
    "{ okl check --change; }",
    "(okl check --change)",
    "! okl check --change",
    "if okl check --change; then :; fi",
    "while okl check --change; do break; done",
    "okl check --change=main",
    "`okl check --change`",
])
def test_an_executed_command_starts_the_review(tmp_path, command):
    """okl as the command word: bare, by path, through python, through the variable a script keeps it in."""
    assert reviewcmd.is_review_command(command)
    t = write(tmp_path, [user(0, "x"), turn(20, "m1", call("tu", "Bash", command=command), usage=(5, 5, 5, 5)),
                         result(21, "tu", REVIEW_OUT)])

    assert reviewlog.read_review(t).ran is True


def test_the_review_starts_at_the_executed_command_not_at_an_earlier_mention(tmp_path):
    """A grep for the command comes first and costs tokens; the window opens at the run after it."""
    t = write(tmp_path, [
        user(0, "x"), feedback(5),
        turn(10, "m0", call("g", "Bash", command="grep -rn 'okl check --change' docs"), usage=(500, 0, 0, 0)),
        result(11, "g", "docs/COMMANDS.md:106:okl check --change [BASE]"),
        turn(100, "m1", call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        result(101, "tu-rev", REVIEW_OUT),
        turn(160, "m2", say("done"), usage=(2, 2, 2, 2))])

    r = reviewlog.read_review(t)

    assert (r.ran, r.tokens, r.duration_s) == (True, 4 + 8, 60)


# --- the review's window -------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [typed, user], ids=["typed (origin human)", "older shape (no origin)"])
def test_a_later_unrelated_turn_is_not_the_review(tmp_path, prompt):
    """A person's next prompt ends the review, in the shape 2.1.302 writes it (`origin` human) and in an
    older one. The work after it, with its own sub-agent that opens a lesson and edits a file, changes
    neither the tokens, the time nor the checks. The review's own sub-agents are still pending when it
    comes (nothing reported them back), and it ends the review all the same."""
    root = repo_root(tmp_path)
    later = call("tu-later", "Agent", prompt="build the export; first okl show les-b", model="opus")
    tail = [turn(300, "m4", say("done"), usage=(5, 5, 5, 5)),
            prompt(7200, "now build the export feature"),
            turn(7210, "m5", later, usage=(5000, 0, 0, 0)), result(7211, "tu-later", "launched", agentId="ccc"),
            blob(later),
            turn(9000, "m6", say("feature done"), usage=(900000, 0, 0, 0))]
    work = [turn(7220, "z1", call("s", "Bash", command="okl show les-b"), usage=(1, 1, 1, 1)),
            turn(7300, "z2", call("w", "Write", file_path=f"{root}/src/export.py"), usage=(1, 1, 1, 1)),
            result(7301, "w", "written")]
    t = two_agents(tmp_path, root, tail=tail)
    sub = t.parent / "sess-1" / "subagents"
    (sub / "agent-ccc.jsonl").write_text("\n".join(work) + "\n")
    (sub / "agent-ccc.meta.json").write_text(json.dumps({"toolUseId": "tu-later", "model": "opus"}))

    r = reviewlog.read_review(t, repo_dir=str(root), known_ids={"les-a", "les-b"})
    base = _read(tmp_path / "again")

    assert [c["agent"] for c in r.checks] == ["aaa", "bbb"]
    assert (r.tokens, r.duration_s) == (base.tokens, base.duration_s) == (172, 190)
    assert all("les-b" not in c["lessons"] or c["agent"] == "bbb" for c in r.checks)
    assert [c["edited"] for c in r.checks] == [True, False]


def test_a_stop_hook_summary_ends_the_review_once_every_subagent_has_reported(tmp_path):
    """The session stopped with nothing pending: whatever the agent does after the stop, say a resumed
    turn, is not the review."""
    root = repo_root(tmp_path)
    later = call("tu-late", "Agent", prompt="more work")
    tail = [notification(250, "aaa"), notification(251, "bbb"),
            turn(300, "m4", say("done"), usage=(5, 5, 5, 5)), stop_summary(305),
            turn(400, "m5", later, usage=(7000, 0, 0, 0)), result(401, "tu-late", "launched", agentId="ddd")]

    r = reviewlog.read_review(two_agents(tmp_path, root, tail=tail), repo_dir=str(root))

    assert [c["agent"] for c in r.checks] == ["aaa", "bbb"]
    assert (r.tokens, r.duration_s) == (172, 190)


def test_a_stop_while_a_subagent_is_still_running_does_not_end_the_review(tmp_path):
    """Every Agent call returns at once as async_launched and the agent stops to wait: a stop with a
    launched sub-agent unreported is not the end. One that never reports runs the review to the next
    prompt a person types, or the end of the file."""
    root = repo_root(tmp_path)
    next_one = call("tu-3", "Agent", prompt=shown("les-b"))
    tail = [turn(300, "m4", say("waiting"), usage=(5, 5, 5, 5)), stop_summary(305),
            notification(310, "aaa"),         # aaa reported; bbb never does
            turn(320, "m5", next_one, usage=(1, 1, 1, 1)), result(321, "tu-3", "launched", agentId="eee",
                                                                  status="async_launched"),
            stop_summary(330)]

    r = reviewlog.read_review(two_agents(tmp_path, root, tail=tail), repo_dir=str(root))

    assert [c["agent"] for c in r.checks] == ["aaa", "bbb", "eee"]


def test_a_review_that_launches_stops_and_resumes_per_lesson_is_logged_whole(tmp_path):
    """The shape of every real review: launch, async_launched, stop, a task notification (not a person)
    naming the sub-agent, the next launch, and so on for three lessons, then a last stop. All three
    are checks, with their edits; the work a prompt of the person's starts after it is not."""
    root = repo_root(tmp_path)

    r = reviewlog.read_review(background_review(tmp_path, root), repo_dir=str(root))

    assert [(c["agent"], c["lessons"], c["edited"], c["edited_files"]) for c in r.checks] == [
        ("ag1", ["les-1"], True, ["src/f1.py"]), ("ag2", ["les-2"], True, ["src/f2.py"]),
        ("ag3", ["les-3"], True, ["src/f3.py"])]
    # the tokens: the review command (100), three launches and three waits (4 each), the last message
    # (4), and each sub-agent's two messages (4 each); the late Agent call's 9000 is not there
    assert r.tokens == 100 + 6 * 4 + 4 + 3 * 8
    assert r.duration_s == 420 - 110      # from the review command to the last message


def test_an_unasked_run_before_the_note_is_not_the_asked_review(tmp_path):
    """The agent ran the review on its own, then the Stop hook asked for it and the agent ran it
    again. The first reviewed another state: only the run after the note is logged, with its own
    sub-agents, tokens and time."""
    root = repo_root(tmp_path)
    early = call("tu-early", "Bash", command="okl check --change")
    lead = [turn(20, "e1", early, usage=(500, 0, 0, 0)), result(21, "tu-early", REVIEW_OUT),
            turn(30, "e2", call("tu-old", "Agent", prompt=shown("les-z")), usage=(500, 0, 0, 0)),
            result(31, "tu-old", "launched", agentId="old")]

    r = reviewlog.read_review(two_agents(tmp_path, root, lead=lead), repo_dir=str(root))

    assert (r.asked, r.ran) == (True, True)
    assert [c["agent"] for c in r.checks] == ["aaa", "bbb"]
    assert (r.tokens, r.duration_s) == (172, 190)


def test_a_note_with_no_review_after_it_is_asked_and_not_run(tmp_path):
    """The agent ran the review before the note and not after it: the session was asked, and the review
    it was asked for did not run. The earlier run is not logged as this session's review."""
    t = write(tmp_path, [
        user(0, "x"),
        turn(20, "e1", call("tu-early", "Bash", command="okl check --change"), usage=(500, 0, 0, 0)),
        result(21, "tu-early", REVIEW_OUT),
        feedback(100),
        turn(110, "m1", say("nothing worth recording"), usage=(9, 9, 9, 9))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.loggable) == (True, False, True)
    assert (r.files_changed, r.lessons_listed, r.tokens, r.duration_s, r.checks) == (None, None, None, None, [])


def test_a_subagent_resumed_after_the_window_ends_is_read_only_up_to_the_end(tmp_path):
    """A review sub-agent the person later resumes for other work has that work in its own transcript,
    after the review's end. Its lines up to the end count, and none after."""
    root = repo_root(tmp_path)
    tail = [turn(300, "m4", say("done"), usage=(5, 5, 5, 5)), typed(400, "now something else")]
    t = two_agents(tmp_path, root, tail=tail)
    resumed = [turn(500, "r1", call("e9", "Edit", file_path=f"{root}/src/other.py"), usage=(3000, 0, 0, 0)),
               result(501, "e9", "ok"),
               turn(502, "r2", call("s9", "Bash", command="okl show les-z; pytest tests/test_x.py"),
                    usage=(3000, 0, 0, 0)),
               result(503, "s9", "1 passed")]
    agent_a = t.parent / "sess-1" / "subagents" / "agent-aaa.jsonl"
    agent_a.write_text(agent_a.read_text() + "\n".join(resumed) + "\n")

    r = reviewlog.read_review(t, repo_dir=str(root), known_ids={"les-a", "les-b", "les-z"})

    a, _b = r.checks
    assert (a["lessons"], a["edited_files"], len(a["tests"])) == (["les-a"], ["src/x.py"], 1)
    assert (r.tokens, r.duration_s) == (172, 190)


def test_who_is_a_person(tmp_path):
    """A prompt a person typed carries `origin` human. A task notification, another session's message
    and any other origin are not a person, whatever their text; with no origin, the text decides."""
    def line(**kw):
        return json.loads(user(0, kw.pop("text", "do the next thing"), **kw))
    is_person = reviewlog._is_human_prompt

    assert is_person(line(origin={"kind": "human"}))
    assert is_person(line(origin={"kind": "human"}, text="<task-notification> a person may paste anything"))
    assert not is_person(line(origin={"kind": "task-notification"}))
    assert not is_person(line(origin={"kind": "peer"}, isMeta=False))
    assert not is_person(line(origin={"kind": "system"}))
    assert not is_person(line(origin="human"))                       # not the shape 2.1.302 writes
    assert is_person(line())                                          # an older transcript
    assert not is_person(line(text="<task-notification>done</task-notification>"))
    assert not is_person(line(text="Stop hook feedback: ..."))
    assert not is_person(line(isMeta=True))
    assert not is_person(line(text="   "))
    assert not is_person(json.loads(result(0, "t", "text")))          # a tool result


def test_lines_no_person_wrote_do_not_end_the_review(tmp_path):
    """A task notification, a reminder, the hook's feedback, a peer's message and a tool result are all
    user lines, and none is a prompt: the review goes on past them."""
    root = repo_root(tmp_path)
    second = call("tu-a3", "Agent", prompt=shown("les-b"))
    tail = [notification(200, "aaa"),
            user(201, "<system-reminder>a reminder</system-reminder>", isMeta=True),
            feedback(202),
            user(203, "<agent-message>a peer says hello</agent-message>", isMeta=True, origin={"kind": "peer"}),
            turn(210, "m5", second, usage=(1, 1, 1, 1)), result(211, "tu-a3", "launched", agentId="eee"),
            turn(300, "m4", say("done"), usage=(5, 5, 5, 5))]

    r = reviewlog.read_review(two_agents(tmp_path, root, tail=tail), repo_dir=str(root))

    assert [c["agent"] for c in r.checks] == ["aaa", "bbb", "eee"]


# --- the shape Claude Code 2.1.302 writes ----------------------------------------------------------

def test_a_blob_line_repeating_a_refused_edit_does_not_make_it_an_edit(tmp_path):
    """2.1.302 writes an `api-request-blob` line that repeats an assistant message's tool_use after its
    result. Read as a call, it re-opens an edit the tool refused, and the sub-agent edited nothing."""
    root = repo_root(tmp_path)
    edit = call("e1", "Edit", file_path=f"{root}/src/x.py", old_string="a", new_string="b")
    run = call("t1", "Bash", command="pytest tests/test_x.py")
    agent = [turn(40, "x1", edit, usage=(1, 1, 1, 1)),
             result(41, "e1", "<tool_use_error>String to replace not found</tool_use_error>", error=True),
             blob(edit),
             turn(50, "x2", run, usage=(1, 1, 1, 1)), result(51, "t1", "3 passed in 0.1s"), blob(run)]
    t = write(tmp_path, [*start_review(),
                         turn(120, "m2", call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
                         result(121, "tu-a", "launched", agentId="fff")], {"fff": (None, agent)})

    (c,) = reviewlog.read_review(t, repo_dir=str(root)).checks

    assert c["edited"] is False and c["edited_files"] == [] and c["edited_outside"] == 0
    assert c["tests"] == [{"runner": "pytest", "targets": ["tests/test_x.py"], "outcome": "passed"}]   # once


def test_a_call_counts_once_in_the_main_transcript_too(tmp_path):
    """The blob that repeats the review command and the Agent call neither starts a second review
    nor makes a second check."""
    rev = call("tu-rev", "Bash", command="okl check --change")
    agent_call = call("tu-a", "Agent", prompt="p")
    t = write(tmp_path, [user(0, "x"), feedback(5),
                         turn(10, "m1", rev, usage=(1, 1, 1, 1)), result(11, "tu-rev", REVIEW_OUT), blob(rev),
                         turn(20, "m2", agent_call, usage=(1, 1, 1, 1)),
                         result(21, "tu-a", "launched", agentId="ggg"), blob(agent_call), blob(agent_call)])

    r = reviewlog.read_review(t)

    assert len(r.checks) == 1 and (r.files_changed, r.lessons_listed) == (4, 12)


# --- sub-agents that cannot be read ----------------------------------------------------------------

def test_a_subagent_whose_meta_file_is_missing_is_found_by_the_agent_id_the_call_returned(tmp_path):
    """The meta file ties a sub-agent to its call by tool id; without it the call's own result names
    the agent, and the model comes from the sub-agent's transcript."""
    agent = [turn(40, "c1", call("x", "Bash", command="okl show les-c"), usage=(1, 1, 1, 1),
                  model="claude-sonnet-4-6"), result(41, "x", "text")]
    t = write(tmp_path, [*start_review(),
                         turn(130, "m2", call("tu-a", "Agent", prompt="check it"), usage=(1, 1, 1, 1)),
                         result(131, "tu-a", "launched", agentId="ccc")], {"ccc": (None, agent)})

    (c,) = reviewlog.read_review(t).checks

    assert (c["agent"], c["model"], c["lessons"], c["read"]) == ("ccc", "claude-sonnet-4-6", ["les-c"], True)


def test_a_subagent_with_neither_meta_nor_transcript_is_recorded_as_unread(tmp_path):
    """What cannot be read is left out, not guessed: no edit is claimed either way, and the lesson
    its prompt carried (as `okl show` prints it) is still named."""
    t = write(tmp_path, [
        user(0, "x"),
        turn(20, "m1", call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        result(21, "tu-rev", REVIEW_OUT),
        turn(30, "m2", call("tu-a", "Agent", prompt=shown("les-z"), model="haiku"), usage=(1, 1, 1, 1)),
        result(31, "tu-a", "plain text, no agent id")])

    (c,) = reviewlog.read_review(t).checks

    assert (c["agent"], c["read"], c["edited"], c["lessons"], c["tokens"], c["model"]) == (
        None, False, False, ["les-z"], None, "haiku")


def test_a_meta_file_whose_transcript_is_missing_is_unread(tmp_path):
    """The meta file names the agent and its model, but with no transcript nothing else is known."""
    t = write(tmp_path, [
        user(0, "x"),
        turn(20, "m1", call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        result(21, "tu-rev", REVIEW_OUT),
        turn(30, "m2", call("tu-a", "Task", prompt=shown("les-a")), usage=(1, 1, 1, 1))],
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


# --- the model -------------------------------------------------------------------------------------

def test_the_model_is_the_one_the_subagent_ran_on_and_inherit_names_none(tmp_path):
    """The transcript's own model first, then the meta file's; `inherit` is not a model, so it is null."""
    def agent(model, meta_model):
        return ({"toolUseId": "tu-a", "model": meta_model},
                [turn(40, "c1", say("hi"), usage=(1, 1, 1, 1), model=model)] if model else [user(40, "no reply")])

    def model_of(name, spec):
        t = write(tmp_path, [*start_review(),
                             turn(130, "m2", call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1))],
                  {"aaa": spec}, session=name)
        return reviewlog.read_review(t).checks[0]["model"]

    assert model_of("full", agent("claude-sonnet-4-6", "opus")) == "claude-sonnet-4-6"
    assert model_of("alias", agent(None, "sonnet")) == "sonnet"
    assert model_of("inherit", agent(None, "inherit")) is None
    assert model_of("synthetic", agent("<synthetic>", "inherit")) is None
    assert model_of("both", agent("claude-opus-5-5", "inherit")) == "claude-opus-5-5"


# --- what is kept ----------------------------------------------------------------------------------

def _one_agent(tmp_path, lines):
    """A review whose one sub-agent, `eee`, has these lines."""
    return write(tmp_path, [*start_review(),
                            turn(30, "m2", call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
                            result(31, "tu-a", "launched", agentId="eee")], {"eee": (None, lines)})


def test_an_edit_the_tool_refused_is_not_an_edit_and_the_mcp_tool_counts_as_opened(tmp_path):
    """A call whose result is an error changed nothing; `okl_get`'s id is a lesson opened."""
    root = repo_root(tmp_path)
    t = _one_agent(tmp_path, [
        turn(40, "e1", call("x1", "Edit", file_path=f"{root}/a.py"), usage=(1, 1, 1, 1)),
        result(41, "x1", "String to replace not found", error=True),
        turn(42, "e2", call("x2", "mcp__okl__okl_get", id="les-a"), usage=(1, 1, 1, 1))])

    (c,) = reviewlog.read_review(t, repo_dir=str(root)).checks

    assert c["edited"] is False and c["lessons"] == ["les-a"]


def test_a_call_with_no_result_is_not_counted(tmp_path):
    """The log is evidence for a default, so a call nothing answered is not an edit, and undercounting
    is the safer error: a later stop reads the session again. A test run with no result is unknown."""
    root = repo_root(tmp_path)
    t = _one_agent(tmp_path, [
        turn(40, "e1", call("x1", "Edit", file_path=f"{root}/src/a.py"), usage=(1, 1, 1, 1)),
        turn(41, "e2", call("x2", "Bash", command="pytest tests/test_x.py"), usage=(1, 1, 1, 1))])

    (c,) = reviewlog.read_review(t, repo_dir=str(root)).checks

    assert (c["edited"], c["edited_files"], c["edited_outside"]) == (False, [], 0)
    assert c["tests"] == [{"runner": "pytest", "targets": ["tests/test_x.py"], "outcome": "unknown"}]


def test_a_path_outside_the_repository_is_a_count_never_a_path(tmp_path):
    """An edit elsewhere (a home directory, a scratch folder) is counted, not named, and an edit in
    the repository is the one that makes `edited`."""
    root = repo_root(tmp_path)
    t = _one_agent(tmp_path, [
        turn(40, "e1", call("x1", "Edit", file_path="/home/jane/secret-project/notes.md"), usage=(1, 1, 1, 1)),
        result(41, "x1", "edited"),
        turn(42, "e2", call("x2", "Write", file_path=f"{root}/../elsewhere.py"), usage=(1, 1, 1, 1)),
        result(43, "x2", "written"),
        turn(44, "e3", call("x3", "Write", file_path=f"{root}/src/in.py"), usage=(1, 1, 1, 1)),
        result(45, "x3", "written")])

    (c,) = reviewlog.read_review(t, repo_dir=str(root)).checks

    assert (c["edited"], c["edited_files"], c["edited_outside"]) == (True, ["src/in.py"], 2)
    assert "jane" not in json.dumps(c) and "elsewhere" not in json.dumps(c)


def test_an_edit_only_outside_the_repository_is_not_an_edit_to_follow(tmp_path):
    """The report counts checks followed by an edit in the repository. A sub-agent that wrote only to /tmp
    left the code as it was: `edited` is False, and the edit is a count beside it."""
    root = repo_root(tmp_path)
    t = _one_agent(tmp_path, [
        turn(40, "e1", call("x1", "Write", file_path="/tmp/scratch-notes.md"), usage=(1, 1, 1, 1)),
        result(41, "x1", "written")])

    (c,) = reviewlog.read_review(t, repo_dir=str(root)).checks

    assert (c["edited"], c["edited_files"], c["edited_outside"]) == (False, [], 1)


def test_a_link_into_the_repository_is_inside_and_a_link_out_of_it_is_not(tmp_path):
    """Paths are compared as real paths, so `/tmp` and `/private/tmp` agree on a Mac: here a link
    to the repository stands in, and a link out of it."""
    root = repo_root(tmp_path)
    outside = tmp_path / "elsewhere"; outside.mkdir()
    (tmp_path / "via").symlink_to(root)
    (root / "escape").symlink_to(outside)

    assert reviewcmd.inside(f"{tmp_path}/via/src/a.py", str(root)) == "src/a.py"
    assert reviewcmd.inside(f"{root}/src/a.py", str(tmp_path / "via")) == "src/a.py"
    assert reviewcmd.inside(f"{root}/escape/a.py", str(root)) is None
    assert reviewcmd.inside(f"{tmp_path}/work/repo2/a.py", str(root)) is None
    assert reviewcmd.inside("src/a.py", str(root)) == "src/a.py" and reviewcmd.inside("../a.py", str(root)) is None
    assert reviewcmd.inside("/anywhere/a.py", None) is None


def test_one_line_nested_past_the_parser_costs_that_line_and_not_the_reading(tmp_path):
    """A line of JSON nested deeper than the parser can hold raises RecursionError, which would end
    the reading; it is dropped and the rest is read."""
    deep = "[" * 200_000 + "]" * 200_000
    t = write(tmp_path, [*start_review(), deep,
                         turn(120, "m2", call("tu-a", "Agent", prompt=shown("les-a")), usage=(1, 1, 1, 1))])

    r = reviewlog.read_review(t)

    assert (r.readable, r.asked, r.ran, r.files_changed) == (True, True, True, 4)
    assert [c["lessons"] for c in r.checks] == [["les-a"]]       # the line after the deep one is read


def test_only_lessons_the_store_has_reach_a_row(tmp_path):
    """A command line is session text: an id that is no lesson here, or no id at all, is dropped."""
    t = write(tmp_path, [
        user(0, "x"),
        turn(20, "m1", call("tu-rev", "Bash", command="okl check --change"), usage=(1, 1, 1, 1)),
        result(21, "tu-rev", REVIEW_OUT),
        turn(30, "m2", call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
        result(31, "tu-a", "launched", agentId="fff")], {"fff": (None, [
            turn(40, "f1", call("x1", "Bash", command="okl show les-a; okl show 'rm -rf /'; okl show nope"),
                 usage=(1, 1, 1, 1))])})

    (c,) = reviewlog.read_review(t, known_ids={"les-a"}).checks
    (open_c,) = reviewlog.read_review(t).checks

    assert c["lessons"] == ["les-a"]
    # without the store only an id's shape is held: `nope` passes it, a quoted sentence does not
    assert open_c["lessons"] == ["les-a", "nope"]


def test_a_row_holds_no_code_and_no_session_text(tmp_path):
    """Ids, paths, counts, model names and booleans: not the edit's text, not the sub-agent's description."""
    r = _read(tmp_path)

    stored = json.dumps([r.checks, r.session, r.files_changed])
    assert not any(w in stored for w in ("SECRET", "OLDTEXT", "launched", "fixed"))


# a path that exists for each name a command line can hide a secret in: the existence test alone
# would keep them, so only skipping the flag's value, and what follows `--`, keeps them out
_SECRET_DIRS = ["api_key", "s3cr3t", "jane.doe@corp.com", "TestLogin", "tests"]


@pytest.mark.parametrize(("command", "expected"), [
    ("mvn -Ddb.password=hunter2 -Dsonar.login=sqp_abc123 test", ("mvn test", [])),
    ('pytest -k "api_key/abc"', ("pytest", [])),
    ("pytest tests/test_x.py -- --password s3cr3t/abc", ("pytest", ["tests/test_x.py"])),
    ('npx mocha --grep "jane.doe@corp.com/x" tests/test_x.py', ("mocha", ["tests/test_x.py"])),
    ("go test -run TestLogin/with_password_hunter2 ./...", ("go test", [])),
    ("pytest -m 's3cr3t/abc' tests/test_x.py::test_a", ("pytest", ["tests/test_x.py"])),
    ("jest -t 'api_key/abc' --testNamePattern x tests", ("jest", ["tests"])),
    ("API_TOKEN=sqp_abc123 python3 -m pytest tests/test_x.py", ("pytest", ["tests/test_x.py"])),
])
def test_a_test_run_keeps_a_fixed_runner_and_existing_paths_only(tmp_path, command, expected):
    """The runner is a fixed name, never the matched text; a target is a path that exists in the
    repository; the value of -k, -m, --grep, -run, -t and --test-name-pattern, and everything after
    `--`, is never read; and a secret in the command line is nowhere in the row."""
    root = repo_root(tmp_path)
    for d in _SECRET_DIRS:
        (root / d).mkdir(exist_ok=True)
        (root / d / "abc").write_text("x")
        (root / d / "x").write_text("x")
    (root / "TestLogin" / "with_password_hunter2").write_text("x")
    agent = [turn(40, "x1", call("t1", "Bash", command=command), usage=(1, 1, 1, 1)),
             result(41, "t1", "1 passed in 0.1s")]
    t = write(tmp_path, [*start_review(),
                         turn(130, "m2", call("tu-a", "Agent", prompt="p"), usage=(1, 1, 1, 1)),
                         result(131, "tu-a", "launched", agentId="ggg")], {"ggg": (None, agent)})

    (c,) = reviewlog.read_review(t, repo_dir=str(root)).checks

    (run,) = c["tests"]
    assert (run["runner"], run["targets"]) == expected
    stored = json.dumps(c)
    assert not any(w in stored for w in ("hunter2", "sqp_abc123", "api_key", "s3cr3t", "jane.doe", "TestLogin",
                                         "password", "API_TOKEN"))


@pytest.mark.parametrize(("command", "runner"), [
    ("pytest tests", "pytest"), ("python3 -m pytest tests", "pytest"), ("uv run pytest tests", "pytest"),
    ("npx jest tests", "jest"), ("bunx vitest run tests", "vitest"), ("xargs pytest tests", "pytest"),
    ("pnpm exec jest tests", "jest"), ("yarn exec jest tests", "jest"), ("timeout 60 pytest tests", "pytest"),
    ("FOO=1 python -m pytest tests", "pytest"), ("cd sub && pytest tests", "pytest"),
    ("bash -c 'pytest tests'", "pytest"), ("npm test", "npm test"),
    ("python tool.py --runner pytest", None), ("python -c \"import pytest\"", None),
    ("python3 -m pip install pytest", None), ("node scripts/run.js jest", None),
    ("ls tests/pytest", None), ("echo pytest", None),
])
def test_a_runner_is_the_command_not_a_word_further_along(tmp_path, command, runner):
    """The runner is the command word after the wrappers, the module after `python -m`, or what `npx`,
    `xargs`, `pnpm exec` and `yarn exec` run. Any other word that names one is an argument."""
    root = repo_root(tmp_path)
    for d in ("sub", "tests"):
        (root / d).mkdir(exist_ok=True)

    run = reviewcmd.parse_test_run(command, str(root))

    assert (run[0] if run else None) == runner


def test_a_path_is_read_as_the_command_writes_it(tmp_path):
    """`cd sub && pytest x.py`: x.py is under `sub`, not the repository, so it is not kept; a path that
    is the repository's own is."""
    root = repo_root(tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "x.py").write_text("x = 1\n")

    assert reviewcmd.parse_test_run("cd sub && pytest x.py", str(root)) == ("pytest", [])
    assert reviewcmd.parse_test_run("cd sub && pytest sub/x.py", str(root)) == ("pytest", ["sub/x.py"])


def test_a_shift_in_arithmetic_is_not_a_heredoc():
    """`$((x<<EOF))` is arithmetic. Read as a heredoc it would swallow the lines after it, and with
    them a review command that ran."""
    assert reviewcmd.is_review_command("echo $((x<<EOF))\nokl check --change\nEOF")
    assert not reviewcmd.is_review_command("cat <<EOF\nokl check --change\nEOF")
    assert not reviewcmd.is_review_command("echo $((1<<3)); cat <<EOF\nokl check --change\nEOF")


def test_the_commands_the_parser_recognizes():
    """The lessons `okl show` names, the runner names, and a test run's outcome; a mention is not a run."""
    assert reviewcmd.command_show_ids("okl show a; okl show --format json b && okl show c --format json") == [
        "a", "b", "c"]
    assert reviewcmd.command_show_ids("grep 'okl show a' notes.md; echo okl show b") == []
    assert reviewcmd.text_show_ids("run `okl show les-a` then okl show --format json les-b") == ["les-a", "les-b"]
    for command, runner in [("npm run test", "npm test"), ("yarn test", "yarn test"), ("cargo nextest run", "cargo nextest"),
                            ("cargo test", "cargo test"), ("./gradlew -q test", "gradle test"),
                            ("python3 -m unittest discover", "unittest"), ("py.test -x", "pytest"),
                            ("dotnet test", "dotnet test"), ("make test", "make test"), ("./mvnw verify test", "mvn test")]:
        assert reviewcmd.parse_test_run(command) == (runner, []), command
    assert reviewcmd.parse_test_run("grep -rn pytest docs/") is None
    assert reviewcmd.parse_test_run("ruff check .") is None
    assert reviewcmd.parse_test_run("git commit -m 'pytest passed'") is None
    assert reviewcmd.parse_test_outcome(False, "5 passed in 1s") == "passed"
    assert reviewcmd.parse_test_outcome(False, "5 passed, 1 failed") == "failed"
    assert reviewcmd.parse_test_outcome(True, "Exit code 1") == "failed"
    assert reviewcmd.parse_test_outcome(False, "collected nothing") == "unknown"
    assert reviewcmd.segments("echo 'a; b' && ls | wc\ncat <<EOF\nokl check --change\nEOF\nls") == [
        ["echo", "a; b"], ["ls"], ["wc"], ["cat", "<<EOF"], ["ls"]]
