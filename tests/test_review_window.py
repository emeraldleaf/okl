"""Which review is the one logged, and when it ends (#464, third round).

A note asks for one review. It is the first command that ran `okl check --change` after the note and
before the next prompt a person typed; a prompt first means the request was skipped, and with several
notes in a session the row is the last one's. The review ends at the next typed prompt, or at a
Stop-hook summary at which no sub-agent it started is still running, and Claude Code 2.1.302 reports a
background sub-agent finished in four shapes (tests/review_transcripts.py): all of them release one.
"""
import pytest
from review_transcripts import (
    REVIEW_OUT,
    background_review,
    blob,
    call,
    feedback,
    handback,
    image_prompt,
    notification,
    queue_op,
    queued_command,
    repo_root,
    result,
    say,
    shown,
    start_review,
    stop_summary,
    task_status,
    turn,
    two_agents,
    typed,
    user,
    write,
)

from okl import reviewlog


def _run(sec: int, tid: str = "tu-run", usage: int = 1) -> list[str]:
    """A review command and its output, at `sec`."""
    return [turn(sec, f"r{tid}", call(tid, "Bash", command="okl check --change"), usage=(usage, usage, usage, usage)),
            result(sec + 1, tid, REVIEW_OUT)]


# --- which review a note asks for ----------------------------------------------------------------

@pytest.mark.parametrize(("first", "later"), [
    (lambda s: typed(s, "fix it"), lambda s: typed(s, "no, something else")),
    (lambda s: user(s, "fix it"), lambda s: user(s, "no, something else")),
    (lambda s: typed(s, "fix it"), image_prompt),
], ids=["typed", "older shape", "an image"])
def test_a_prompt_before_the_run_means_the_request_was_skipped(tmp_path, first, later):
    """The person typed before the review ran: the note's request was skipped, and a run after that, which
    reviews work nobody asked it to, is not logged as the session's review."""
    t = write(tmp_path, [first(0), feedback(100), later(200), *_run(300),
                         turn(310, "m2", call("tu-a", "Agent", prompt=shown("les-a")), usage=(1, 1, 1, 1))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.loggable) == (True, False, True)
    assert (r.tokens, r.duration_s, r.checks) == (None, None, [])


def test_with_three_notes_the_last_ones_review_is_the_row(tmp_path):
    """The first note's run, the second note (skipped by a prompt) and the third: the row describes the
    third, with its own sub-agents, tokens and time. The earlier notes and their runs are not logged."""
    root = repo_root(tmp_path)
    lead = [feedback(10), *_run(15, "tu-first", usage=500), typed(20, "now this"),
            feedback(30), typed(40, "and this")]

    r = reviewlog.read_review(two_agents(tmp_path, root, lead=lead), repo_dir=str(root))

    assert (r.asked, r.ran) == (True, True)
    assert [c["agent"] for c in r.checks] == ["aaa", "bbb"]
    assert (r.tokens, r.duration_s) == (111, 190)


def test_three_notes_the_last_skipped_and_an_earlier_one_run_is_asked_and_not_run(tmp_path):
    """The run belongs to the first note, and the last note's request was skipped: asked, not ran. A run
    after the prompt that skipped it is nobody's review."""
    t = write(tmp_path, [
        typed(0, "fix it"), feedback(10), *_run(15, "tu-first", usage=500), typed(20, "now this"),
        feedback(30), typed(40, "and this"), feedback(50), typed(60, "and that"),
        *_run(70, "tu-late", usage=500), turn(80, "m9", call("tu-a", "Agent", prompt=shown("les-a")))])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.tokens, r.checks) == (True, False, None, [])


def test_a_notes_two_lines_are_one_request(tmp_path):
    """The hook's summary and its feedback both carry the note: read as two notes the second would throw
    away nothing (no run is open), but the review after them must still be read."""
    root = repo_root(tmp_path)
    lead = [stop_summary(99, note=True)]

    r = reviewlog.read_review(two_agents(tmp_path, root, lead=lead), repo_dir=str(root))

    assert (r.asked, r.ran, [c["agent"] for c in r.checks]) == (True, True, ["aaa", "bbb"])


def test_a_run_before_any_note_keeps_the_rule_it_had(tmp_path):
    """No note in the session: the first command that ran the review is the review, asked or not."""
    t = write(tmp_path, [typed(0, "fix it"), *_run(10, usage=3), typed(50, "next"), *_run(60, "tu-2", usage=500)])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran, r.tokens, r.duration_s) == (False, True, 9, 1)


def test_a_prompt_that_mentions_a_tool_result_still_skips_the_request(tmp_path):
    """In a transcript of the older shape a user line is a prompt unless it is a result, which only the
    parsed line says. A byte test for the words would have dropped this person's question unread, and the
    run after it would have been logged as the note's review."""
    t = write(tmp_path, [user(0, "fix it"), feedback(100),
                         user(200, 'what is a "tool_result" in a transcript?'), *_run(300)])

    r = reviewlog.read_review(t)

    assert (r.asked, r.ran) == (True, False)


def test_a_prompt_that_mentions_a_tool_result_ends_an_open_window(tmp_path):
    """And one typed inside the review ends it, the later work not counted."""
    root = repo_root(tmp_path)
    tail = [turn(300, "m4", say("done"), usage=(5, 5, 5, 5)),
            user(400, 'why did the "tool_result" come back empty?'),
            turn(410, "m5", call("tu-late", "Agent", prompt="more"), usage=(5000, 0, 0, 0))]

    r = reviewlog.read_review(two_agents(tmp_path, root, tail=tail, older=True), repo_dir=str(root))

    assert [c["agent"] for c in r.checks] == ["aaa", "bbb"]
    assert r.tokens == 111


# --- who typed ------------------------------------------------------------------------------------------

def test_who_typed_a_prompt():
    """A compact summary is not one; once a transcript has shown an `origin`, a line without one is not
    one; an image-only prompt of `kind: human` is."""
    import json
    person = reviewlog._is_human_prompt

    def line(**kw):
        return json.loads(user(0, kw.pop("text", "carry on"), **kw))
    assert person(line(), origin_era=False)
    assert not person(line(), origin_era=True)
    assert not person(line(isCompactSummary=True))
    assert not person(line(isCompactSummary=True, origin={"kind": "human"}))
    assert person(json.loads(image_prompt(0)), origin_era=True)
    assert person(line(origin={"kind": "human"}), origin_era=True)


# --- a sub-agent's completion, in every shape ---------------------------------------------------------

def _released_by(tmp_path, report, session="sess-1"):
    """A review whose one background sub-agent `aaa` is reported by `report` (a list of lines) between two
    stops, then the review's last message and stop, then work that is not the review's."""
    launch = call("tu-a1", "Agent", prompt=shown("les-a"), model="sonnet")
    later = call("tu-late", "Agent", prompt=shown("les-z"))
    lines = [*start_review(),
             turn(120, "m2", launch, usage=(1, 1, 1, 1)),
             result(121, "tu-a1", "launched", agentId="aaa", status="async_launched"), blob(launch),
             turn(122, "m3", say("waiting"), usage=(1, 1, 1, 1)), stop_summary(123),
             *report,
             turn(300, "m4", say("done"), usage=(1, 1, 1, 1)), stop_summary(301),
             turn(400, "m5", later, usage=(5000, 0, 0, 0)), result(401, "tu-late", "launched", agentId="zzz",
                                                                   status="async_launched")]
    agent = [turn(130, "s1", call("sh", "Bash", command="okl show les-a"), usage=(1, 1, 1, 1)),
             result(131, "sh", "[les-a] Rule")]
    return write(tmp_path, lines, {"aaa": ({"toolUseId": "tu-a1", "model": "sonnet"}, agent)}, session=session)


SHAPES = {
    "a user line, a task notification": lambda: [notification(200, "aaa")],
    "a user line, by the tool_use id alone": lambda: [notification(200, "other", tool_id="tu-a1")],
    "a user line, a peer's hand-back": lambda: [handback(200, "aaa")],
    "an attachment, queued_command": lambda: [queued_command(200, "aaa")],
    "an attachment, task_status completed": lambda: [task_status(150, "aaa", "running"), task_status(200, "aaa", "completed")],
    "a queue-operation line": lambda: [queue_op(200, "aaa")],
    "a failed sub-agent": lambda: [queued_command(200, "aaa", status="failed")],
    "a killed one": lambda: [notification(200, "aaa", status="killed")],
    "a stopped one": lambda: [queue_op(200, "aaa", status="stopped")],
    "a notification with no status": lambda: [notification(200, "aaa", status=None)],
}


@pytest.mark.parametrize("shape", SHAPES)
def test_every_shape_a_completion_arrives_in_releases_the_subagent(tmp_path, shape):
    """The stop after the report ends the review: the work that follows is not counted. Had the report
    not released `aaa`, the window would have run on, and taken the later Agent call as a check."""
    r = reviewlog.read_review(_released_by(tmp_path, SHAPES[shape]()), known_ids={"les-a", "les-z"})

    assert [c["agent"] for c in r.checks] == ["aaa"]
    # the review command (60), a launch, a wait and the last message (3 each), the sub-agent's one message (3)
    assert r.tokens == 60 + 3 * 3 + 3 and r.duration_s == 300 - 110


@pytest.mark.parametrize("report", [
    [task_status(200, "aaa", "running")],
    [notification(200, "aaa", status="running")],
    [queued_command(200, "aaa", status="progress")],
    [queue_op(200, "aaa", status="running")],
    [user(200, "did aaa finish? tu-a1 and aaa are what I launched")],
    [user(200, "I mention tu-a1 in passing", origin={"kind": "peer"}, isMeta=True)],
    [queue_op(200, "someone-else")],
], ids=["task_status running", "notification running", "queued_command progress", "queue-operation running",
        "a user line that only mentions it", "a peer that only mentions it", "another agent's"])
def test_a_report_that_is_not_a_completion_releases_nothing(tmp_path, report):
    """A task still running, a status that is not a terminal one, a line that merely names the id, and
    another sub-agent's completion all leave `aaa` pending: the stop that follows is not the end, and the
    window goes on to the next call."""
    r = reviewlog.read_review(_released_by(tmp_path, report), known_ids={"les-a", "les-z"})

    assert [c["agent"] for c in r.checks] == ["aaa", "zzz"]


def test_one_finished_as_a_queued_command_mid_turn_and_one_as_a_user_line(tmp_path):
    """The reviewer's probe: A reports as a `queued_command` attachment in the middle of a turn, B as a
    user line, and unrelated work follows with no prompt typed. The row is the review's own two checks,
    its own tokens and its own time, not the work after it."""
    root = repo_root(tmp_path)
    a = call("tu-a", "Agent", prompt=shown("les-a"))
    b = call("tu-b", "Agent", prompt=shown("les-b"))
    unrelated = call("tu-x", "Agent", prompt="build the next feature; first okl show les-z")
    lines = [*start_review(),
             turn(120, "m2", a, usage=(1, 1, 1, 1)), result(121, "tu-a", "launched", agentId="aaa", status="async_launched"),
             turn(122, "m3", b, usage=(1, 1, 1, 1)), result(123, "tu-b", "launched", agentId="bbb", status="async_launched"),
             turn(130, "m4", say("waiting"), usage=(1, 1, 1, 1)), stop_summary(131),
             queued_command(200, "aaa"),
             turn(205, "m5", say("aaa is in"), usage=(1, 1, 1, 1)), stop_summary(206),     # b is still out
             notification(250, "bbb"),
             turn(260, "m6", say("both are in"), usage=(1, 1, 1, 1)), stop_summary(261),
             # work that is not the review's, with nothing a person typed
             turn(300, "m7", unrelated, usage=(5000, 0, 0, 0)),
             result(301, "tu-x", "launched", agentId="ccc", status="async_launched"),
             queued_command(400, "ccc"),
             turn(500, "m8", say("feature done"), usage=(900000, 0, 0, 0)), stop_summary(501)]
    agents = {aid: ({"toolUseId": tid, "model": "sonnet"},
                    [turn(130, f"s{aid}", call(f"sh{aid}", "Bash", command=f"okl show {lesson}"), usage=(1, 1, 1, 1)),
                     result(131, f"sh{aid}", "[x] Rule"),
                     turn(132, f"w{aid}", call(f"ed{aid}", "Edit", file_path=f"{root}/src/{aid}.py"), usage=(1, 1, 1, 1)),
                     result(133, f"ed{aid}", "ok")])
              for aid, tid, lesson in (("aaa", "tu-a", "les-a"), ("bbb", "tu-b", "les-b"))}
    agents["ccc"] = ({"toolUseId": "tu-x", "model": "opus"},
                     [turn(310, "sc", call("shc", "Bash", command="okl show les-z"), usage=(1, 1, 1, 1)),
                      turn(320, "ec", call("edc", "Write", file_path=f"{root}/src/feature.py"), usage=(1, 1, 1, 1)),
                      result(321, "edc", "written")])

    r = reviewlog.read_review(write(tmp_path, lines, agents), repo_dir=str(root), known_ids={"les-a", "les-b", "les-z"})

    assert [(c["agent"], c["lessons"], c["edited"]) for c in r.checks] == [
        ("aaa", ["les-a"], True), ("bbb", ["les-b"], True)]
    # the review command (60), two launches and three more messages (3 each), each sub-agent's two (3 each)
    assert r.tokens == 60 + 5 * 3 + 2 * 2 * 3
    assert r.duration_s == 260 - 110


# --- a launch that failed -----------------------------------------------------------------------------

def test_an_agent_call_that_came_back_as_an_error_started_nothing(tmp_path):
    """No sub-agent ran: the call is no check, its lessons are not counted, it is not pending (the stop
    after it ends the review), and it is counted apart."""
    bad = call("tu-bad", "Agent", prompt=shown("les-x"))
    good = call("tu-ok", "Agent", prompt=shown("les-a"))
    later = call("tu-late", "Agent", prompt=shown("les-y"))
    lines = [*start_review(),
             turn(120, "m2", bad, usage=(1, 1, 1, 1)),
             result(121, "tu-bad", "Agent type 'nope' not found", error=True),
             turn(125, "m3", good, usage=(1, 1, 1, 1)), result(126, "tu-ok", "done"),
             turn(130, "m4", say("done"), usage=(1, 1, 1, 1)), stop_summary(131),
             turn(200, "m5", later, usage=(1, 1, 1, 1)), result(201, "tu-late", "done")]

    r = reviewlog.read_review(write(tmp_path, lines))

    assert [c["lessons"] for c in r.checks] == [["les-a"]]
    assert r.failed_launches == 1


@pytest.mark.parametrize("report", [
    notification, queued_command, queue_op, handback, lambda sec, aid: task_status(sec, aid, "completed")],
    ids=["a user line", "queued_command", "queue-operation", "a peer's hand-back", "task_status"])
def test_a_sequential_background_review_logs_all_three_whatever_shape_its_completions_take(tmp_path, report):
    """The shape of every real review, a launch, a stop, a report, the next launch: all three lessons are
    checks, and not the work after the last stop."""
    root = repo_root(tmp_path)

    r = reviewlog.read_review(background_review(tmp_path, root, report=report), repo_dir=str(root))

    assert [c["agent"] for c in r.checks] == ["ag1", "ag2", "ag3"]
    assert r.duration_s == 420 - 110


def test_a_refused_review_command_is_no_run_and_the_request_stays_open(tmp_path):
    """The review command came back as an error (the person refused it, or okl could not run): no review
    ran, so the note's request is still open, and the run after it is the review (found by the 0.18.0
    sweep). With no run after it, the session is asked and not ran."""
    refused = [turn(15, "rref", call("tu-ref", "Bash", command="okl check --change"), usage=(500, 500, 500, 500)),
               result(16, "tu-ref", "Permission denied", error=True)]
    alone = write(tmp_path, [typed(0, "fix it"), feedback(10), *refused, typed(30, "never mind")])
    assert (reviewlog.read_review(alone).ran, reviewlog.read_review(alone).tokens) == (False, None)

    then = write(tmp_path, [typed(0, "fix it"), feedback(10), *refused, *_run(20, "tu-ok")], session="sess-2")
    r = reviewlog.read_review(then)

    assert (r.asked, r.ran) == (True, True)
    assert (r.tokens, r.duration_s) == (3, 1)    # the run's own, not the refused call's 1,500
