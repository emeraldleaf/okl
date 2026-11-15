"""Synthetic Claude Code transcripts for the review log's tests (#464).

Hand-written in the shape Claude Code 2.1.302 saves, never copied from a session: one line per
content block, each assistant line carrying its message's usage, tool results as user lines, the
main transcript beside `<session>/subagents/agent-<id>.jsonl` and `.meta.json`, and the
`api-request-blob` lines that re-carry an assistant message's tool calls after their results.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

T0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=UTC)
REVIEW_OUT = ("## OKL review after writing — r · 4 file(s) changed since main (merge base abc1234), "
              "committed or not\n\nThis review lists 12 lesson(s) in about 1 KB. Read all of it before "
              "you pick.\n")
NOTE = ("REVIEW AFTER WRITING (on in this repo): before you answer the question below, check the code "
        "this session wrote against the lessons. Run `okl check --change` and follow its steps.")


def at(sec: int) -> str:
    """The timestamp `sec` seconds into the session."""
    return (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def user(sec: int, text: str, **extra) -> str:
    """A user line with no `origin`, the shape of an older transcript: a prompt a person typed
    unless `extra` says otherwise (isMeta, origin)."""
    return json.dumps({"type": "user", "timestamp": at(sec), "message": {"role": "user", "content": text},
                       **extra})


def typed(sec: int, text: str) -> str:
    """A prompt a person typed, as 2.1.302 writes it: `origin: {"kind": "human"}`."""
    return user(sec, text, origin={"kind": "human"})


def notification(sec: int, agent_id: str) -> str:
    """The user line that reports a background sub-agent back: not a person (its origin says so) and
    not marked meta, and it names the agent in a `<task-id>`."""
    return user(sec, f"<task-notification><task-id>{agent_id}</task-id><status>completed</status>"
                     "</task-notification>", origin={"kind": "task-notification"})


def feedback(sec: int, note: bool = True) -> str:
    """The Stop hook's blocking feedback, as Claude Code writes it into the transcript."""
    text = ('Stop hook feedback:\n["$CLAUDE_PROJECT_DIR"/.claude/hooks/stop-okl-encode.sh]: '
            + (NOTE + "\n" if note else "") + "ENCODING LOOP — before this session ends: did it surface a lesson?")
    return user(sec, text, isMeta=True)


def stop_summary(sec: int) -> str:
    """The `system` line Claude Code writes when a Stop hook has run: the session stopped."""
    return json.dumps({"type": "system", "subtype": "stop_hook_summary", "timestamp": at(sec),
                       "hookCount": 1, "hookErrors": [], "preventedContinuation": False})


def call(tid: str, name: str, **inp) -> dict:
    """A tool_use block."""
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def say(text: str) -> dict:
    """A text block."""
    return {"type": "text", "text": text}


def turn(sec: int, mid: str, *blocks: dict, usage: tuple[int, int, int, int] = (1, 1, 1, 1),
         model: str = "claude-opus-5-5") -> str:
    """One assistant message: a line per content block, each with the whole message's usage, so a
    message with two blocks must still be counted once."""
    u = dict(zip(("input_tokens", "output_tokens", "cache_creation_input_tokens",
                  "cache_read_input_tokens"), usage, strict=True))
    return "\n".join(json.dumps({"type": "assistant", "timestamp": at(sec), "message": {
        "id": mid, "role": "assistant", "model": model, "content": [b], "usage": u}}) for b in blocks)


def result(sec: int, tid: str, text: str, *, error: bool = False, **tool_use_result) -> str:
    """A tool result, a user line; `tool_use_result` is what Claude Code adds beside it (agentId)."""
    line = {"type": "user", "timestamp": at(sec), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": error}]}}
    if tool_use_result:
        line["toolUseResult"] = tool_use_result
    return json.dumps(line)


def blob(*blocks: dict) -> str:
    """The `api-request-blob` line 2.1.302 writes after a result, repeating the message's tool calls.
    It has no timestamp and no usage, and a reader that counts its calls counts every call twice."""
    return json.dumps({"type": "api-request-blob", "sessionId": "s", "hash": "h",
                       "message": {"role": "assistant", "content": list(blocks)}})


def write(tmp_path: Path, main_lines: list[str], agents: dict | None = None, session: str = "sess-1") -> Path:
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


def shown(lesson: str) -> str:
    """A lesson's text as `okl show` prints it, pasted into a sub-agent's prompt."""
    return f"[{lesson}] Rule · org · created 2026-11-01 10:00Z\n  a title\n  fix: do the thing"


def repo_root(tmp_path: Path) -> Path:
    """A repository directory with a test file in it, as the sessions' commands name it."""
    r = tmp_path / "work" / "repo"
    (r / "tests").mkdir(parents=True)
    (r / "tests" / "test_x.py").write_text("x = 1\n")
    return r


def start_review(sec: int = 110) -> list[str]:
    """The lines that start a review: the person's prompt, the hook's note, the review command and
    its output, with the command repeated by a blob line as 2.1.302 writes it."""
    rev = call("tu-rev", "Bash", command="okl check --change")
    return [typed(0, "fix the bug"), feedback(sec - 10),
            turn(sec, "m1", rev, usage=(10, 20, 30, 40)), result(sec + 2, "tu-rev", REVIEW_OUT), blob(rev)]


def two_agents(tmp_path: Path, root: Path, tail: list[str] | None = None, lead: list[str] | None = None) -> Path:
    """A review with two sub-agents: `aaa` opens les-a, edits a file and runs a test; `bbb` opens
    les-b and changes nothing. `tail` replaces the lines after the review's last message, and `lead`
    comes before the prompt, the note and the review."""
    a1 = call("tu-a1", "Agent", description="SECRET DESCRIPTION", prompt=shown("les-a"),
              subagent_type="general-purpose")
    a2 = call("tu-a2", "Agent", description="second", prompt="look at les-b")
    main_lines = [
        *(lead or []),
        *start_review(),
        # two blocks, one message: its usage (10 tokens) is on both lines and counts once
        turn(120, "m2", say("starting the first"), a1, usage=(1, 2, 3, 4)),
        result(121, "tu-a1", "launched", agentId="aaa", status="async_launched"), blob(a1),
        turn(122, "m3", a2, usage=(1, 2, 3, 4)),
        result(123, "tu-a2", "launched", agentId="bbb", status="async_launched"), blob(a2),
        *(tail if tail is not None else [turn(300, "m4", say("done"), usage=(5, 5, 5, 5))]),
    ]
    edit = call("e1", "Edit", file_path=f"{root}/src/x.py", new_string="SECRET CODE", old_string="OLDTEXT")
    run = call("t1", "Bash", command="pytest tests/test_x.py -q 2>&1 | tail -3")
    agent_a = [
        turn(130, "a1", call("x1", "Bash", command="okl show les-a"), usage=(1, 1, 1, 1)),
        result(131, "x1", "[les-a] Rule · org"),
        turn(140, "a2", edit, usage=(1, 1, 1, 1)), result(141, "e1", "edited"), blob(edit),
        turn(150, "a3", run, usage=(1, 1, 1, 1)), result(151, "t1", "3 passed in 0.1s"), blob(run),
        turn(160, "a4", say("fixed"), usage=(1, 1, 1, 1)),
    ]
    agent_b = [
        turn(170, "b1", call("y1", "Bash", command="okl show les-b"), usage=(2, 2, 2, 2),
             model="claude-sonnet-4-6"),
        result(171, "y1", "[les-b] Rule · org"),
        turn(250, "b2", say("no bearing"), usage=(2, 2, 2, 2), model="claude-sonnet-4-6"),
    ]
    return write(tmp_path, main_lines, {
        "aaa": ({"toolUseId": "tu-a1", "model": "opus", "pickedEffortModel": "opus",
                 "description": "SECRET DESCRIPTION"}, agent_a),
        "bbb": ({"toolUseId": "tu-a2", "model": "sonnet"}, agent_b)})


def background_review(tmp_path: Path, root: Path, lessons: int = 3) -> Path:
    """A review as 2.1.302 saved every one: each Agent call returns `async_launched`, the agent stops
    (a Stop-hook summary) until a task notification names the sub-agent, then launches the next, one
    lesson after another, and stops a last time. A prompt the person types afterwards starts other work."""
    main_lines = [*start_review()]
    t = 120
    agents = {}
    for n in range(1, lessons + 1):
        aid, tid = f"ag{n}", f"tu-{n}"
        launch = call(tid, "Agent", prompt=f"check lesson les-{n}: okl show les-{n}", model="sonnet")
        main_lines += [turn(t, f"a{n}", launch, usage=(1, 1, 1, 1)),
                       result(t + 1, tid, "launched", agentId=aid, status="async_launched"), blob(launch),
                       turn(t + 2, f"w{n}", say("waiting for the sub-agent"), usage=(1, 1, 1, 1)),
                       stop_summary(t + 3), notification(t + 60, aid)]
        agents[aid] = ({"toolUseId": tid, "model": "sonnet"}, [
            turn(t + 10, f"s{n}", call(f"sh{n}", "Bash", command=f"okl show les-{n}"), usage=(1, 1, 1, 1)),
            result(t + 11, f"sh{n}", f"[les-{n}] Rule"),
            turn(t + 20, f"e{n}", call(f"ed{n}", "Edit", file_path=f"{root}/src/f{n}.py"), usage=(1, 1, 1, 1)),
            result(t + 21, f"ed{n}", "ok")])
        t += 100
    late = call("tu-late", "Agent", prompt="okl show les-9 then build the feature")
    main_lines += [turn(t, "fin", say("checked every lesson"), usage=(1, 1, 1, 1)), stop_summary(t + 1),
                   typed(t + 600, "now do the next task"),
                   turn(t + 610, "late", late, usage=(9000, 0, 0, 0)),
                   result(t + 611, "tu-late", "launched", agentId="late", status="async_launched")]
    return write(tmp_path, main_lines, agents)
