"""What a review after writing did in a real session, read from a Claude Code transcript (#464).

okl calls no model. The agent runs the review: it runs `okl check --change`, starts a sub-agent per
lesson, and each sub-agent may edit code. Only the session's transcript sees all of it. Claude Code
saves the main transcript as `<projects dir>/<session>.jsonl`, and each sub-agent as
`<projects dir>/<session>/subagents/agent-<id>.jsonl` with an `agent-<id>.meta.json` beside it that
names the main transcript's tool call that started it (`toolUseId`) and the model.

That format is Claude Code's and undocumented, so every read here fails soft: what cannot be read
is left out, and nothing raises into the Stop hook this rides on. A reading holds ids, paths, counts,
model names and booleans only: no code, no command line and no text from the session.

The review is a window of the transcript. It starts at the first command that ran `okl check
--change` after the Stop hook's note (one before the note reviewed another state; without a note,
the first one), and ends at the next prompt a person typed, or at a Stop-hook summary with no
sub-agent it started still pending, whichever comes first. Tokens, time and sub-agents are counted
inside it, and a sub-agent's own lines up to its end: a session that goes on to other work after its
review must not have that work counted as the review's.

Claude Code 2.1.302 also writes `api-request-blob` lines that repeat an assistant message's tool
calls after their results. Only assistant and user lines are read for calls, and a call counts once.

Imports nothing from okl (reviewcmd reads command lines), so the parser has no way to reach the store.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import reviewcmd

NOTE = b"REVIEW AFTER WRITING"        # what the Stop hook's one-line note starts with (core.REVIEW_NOTE)
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
# The call that starts a sub-agent. Claude Code renamed it, so a transcript holds one or the other. Two
# names, not a collection: evals/review_e2e.py, a measurement script kept as it ran, writes the same
# pair out, and tests/test_single_source.py fails on a second copy of a collection.
SUBAGENT_TOOL, SUBAGENT_TOOL_OLD = "Agent", "Task"
# Sanity limits on one sub-agent's lists, so a runaway session cannot grow a row without end.
MAX_LESSONS, MAX_FILES, MAX_TESTS = 100, 100, 50

_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:@+/-]{0,199}")
_AGENT_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_MODEL = re.compile(r"[\w.:/\[\]-]{1,80}")
# `okl show` prints `[<id>] Rule · org · created ...` first; a lesson pasted into a prompt keeps it.
_SHOWN = re.compile(r"^\[([^\]\s]+)\] \w+ · ", re.M)
# The two counts come from the review's own output (core.render_review); a test renders it and
# reads them back, so a change to that wording fails there rather than here, quietly.
_FILES = re.compile(r"(\d+) file\(s\) changed since")
_LISTED = re.compile(r"This review lists (\d+) lesson\(s\)")
# What Claude Code writes as a user line that no person typed.
_NOT_A_PROMPT = ("<task-notification", "<agent-message", "<system-reminder", "Stop hook")


@dataclass
class ReviewReading:
    """What one transcript says about the session's review after writing."""

    session: str
    readable: bool = False             # the transcript could be opened
    asked: bool = False                # the Stop hook's note is in it
    ran: bool = False                  # the agent ran `okl check --change` itself
    files_changed: int | None = None   # from the review's own output, when readable
    lessons_listed: int | None = None
    tokens: int | None = None          # the review's, with its sub-agents'
    duration_s: int | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def loggable(self) -> bool:
        """Whether there is a review, or a request for one, to log: a session with neither says
        nothing about the review, so it gets no row."""
        return self.readable and (self.asked or self.ran)


# --- small readers ---------------------------------------------------------------------------------

def _loads(line: bytes) -> dict[str, Any] | None:
    try:
        d = json.loads(line)
    except (ValueError, RecursionError):        # a line nested past what the parser can hold is lost, not the reading
        return None
    return d if isinstance(d, dict) else None


def _message(d: dict[str, Any]) -> dict[str, Any]:
    m = d.get("message")
    return m if isinstance(m, dict) else {}


def _blocks(d: dict[str, Any]) -> list[dict[str, Any]]:
    """The content blocks of an assistant or user line; no other kind of line carries a call that
    ran (an `api-request-blob` line repeats the calls of a message already written)."""
    if d.get("type") not in ("assistant", "user"):
        return []
    content = _message(d).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(content: Any) -> str:
    """A tool result's text: the string, or its text blocks joined."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def _ts(d: dict[str, Any]) -> float | None:
    raw = d.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _num(v: Any) -> int:
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0


def _model(*candidates: Any) -> str | None:
    """The first candidate that names a model. `inherit` is what a sub-agent says when it takes its
    parent's model, and names none."""
    return next((c for c in candidates if isinstance(c, str) and c != "inherit" and _MODEL.fullmatch(c)), None)


class _Tally:
    """The tokens and the time span of a run of transcript lines.

    Claude Code writes one line per content block of an assistant message, each carrying the
    message's usage, so a message is counted once, by its id, at the largest figure logged for it.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, int] = {}
        self._anonymous = 0
        self.seen = False
        self.last: float | None = None

    def add(self, d: dict[str, Any]) -> None:
        ts = _ts(d)
        if ts is not None:
            self.last = ts if self.last is None else max(self.last, ts)
        m = _message(d)
        usage = m.get("usage")
        if d.get("type") != "assistant" or not isinstance(usage, dict):
            return
        self.seen = True
        total = sum(_num(usage.get(k)) for k in ("input_tokens", "output_tokens",
                                                 "cache_creation_input_tokens", "cache_read_input_tokens"))
        mid = m.get("id")
        if isinstance(mid, str) and mid:
            self._by_id[mid] = max(self._by_id.get(mid, 0), total)
        else:
            self._anonymous += total

    @property
    def tokens(self) -> int:
        return sum(self._by_id.values()) + self._anonymous


# --- the sub-agents ----------------------------------------------------------------------------------

class _AgentScan:
    """What one sub-agent's transcript shows: the lessons it was given or opened, what it edited,
    the tests it ran, its model and its tokens."""

    def __init__(self, root: str | None) -> None:
        self.root = root
        self.lessons: list[str] = []
        self.inside: set[str] = set()        # edited paths in the repository, relative
        self.outside: set[str] = set()       # edited paths elsewhere: only their number is kept
        self.tests: list[dict[str, Any]] = []
        self.model: str | None = None
        self.tally = _Tally()
        self._seen: set[str] = set()                            # tool call ids already counted
        self._edits: dict[str, str] = {}                        # an edit call's id -> its path
        self._runs: dict[str, tuple[str, list[str]]] = {}       # a test call's id -> runner, targets

    def feed(self, d: dict[str, Any]) -> None:
        """Fold one transcript line in."""
        self.tally.add(d)
        if d.get("type") == "assistant":
            self.model = self.model or _model(_message(d).get("model"))
        for b in _blocks(d):
            if b.get("type") == "tool_use":
                self._call(b)
            elif b.get("type") == "tool_result":
                self._result(b)

    def _call(self, b: dict[str, Any]) -> None:
        name, tid, inp = str(b.get("name", "")), b.get("id"), b.get("input")
        if not isinstance(tid, str) or tid in self._seen:
            return
        self._seen.add(tid)
        inp = inp if isinstance(inp, dict) else {}
        if name in EDIT_TOOLS:
            path = inp.get("file_path") or inp.get("notebook_path")
            if isinstance(path, str) and path:
                self._edits[tid] = path
        elif name == "Bash" and isinstance(inp.get("command"), str):
            self.lessons += reviewcmd.command_show_ids(inp["command"])
            run = reviewcmd.parse_test_run(inp["command"], self.root)
            if run:
                self._runs[tid] = run
        elif name.endswith("okl_get") and isinstance(inp.get("id"), str):
            self.lessons.append(inp["id"])

    def _edited(self, path: str) -> None:
        rel = reviewcmd.inside(path, self.root)
        if rel is None:
            self.outside.add(path)
        else:
            self.inside.add(rel)

    def _result(self, b: dict[str, Any]) -> None:
        rid = b.get("tool_use_id")
        if rid in self._edits:
            path = self._edits.pop(rid)
            if not b.get("is_error"):       # an edit the tool refused changed nothing
                self._edited(path)
        if rid in self._runs:
            runner, targets = self._runs.pop(rid)
            self.tests.append({"runner": runner, "targets": targets, "outcome":
                               reviewcmd.parse_test_outcome(bool(b.get("is_error")), _text(b.get("content")))})

    def finish(self) -> dict[str, Any]:
        """The reading. `edited` is an edit inside the repository whose result reported no error: a
        call with no result is not counted, since the log is evidence for a default and undercounting
        is the safer error (a later stop reads the session again). An edit elsewhere is only counted in
        `edited_outside`. A test run with no result is `unknown`."""
        tests = self.tests + [{"runner": r, "targets": t, "outcome": "unknown"}
                              for r, t in self._runs.values()]
        return {"lessons": self.lessons, "edited_files": sorted(self.inside)[:MAX_FILES],
                "edited_outside": len(self.outside), "edited": bool(self.inside),
                "tests": tests[:MAX_TESTS], "tokens": self.tally.tokens, "model": self.model,
                "last": self.tally.last}


def _read_agent(path: Path, root: str | None, until: float | None) -> dict[str, Any] | None:
    """One sub-agent's transcript read, up to `until` (the end of the review's window, when it ended);
    None when the file cannot be opened. A sub-agent the review started and later resumed for other
    work has that work after `until`, and it is not the review's."""
    scan = _AgentScan(root)
    try:
        with path.open("rb") as f:
            for line in f:
                d = _loads(line)
                if d is None:
                    continue
                ts = _ts(d)
                if until is None or ts is None or ts <= until:
                    scan.feed(d)
    except OSError:
        return None
    return scan.finish()


def _metas(sub_dir: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    """Each sub-agent's meta file by the `toolUseId` it names: (agent id, meta)."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    try:
        files = sorted(sub_dir.glob("agent-*.meta.json"))
    except OSError:
        return out
    for f in files:
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tool_id = meta.get("toolUseId") if isinstance(meta, dict) else None
        if isinstance(tool_id, str):
            out[tool_id] = (f.name[len("agent-"):-len(".meta.json")], meta)
    return out


# --- the main transcript -----------------------------------------------------------------------------

def _carries_note(d: dict[str, Any]) -> bool:
    """Whether a transcript line is the Stop hook's feedback with the review note in it, as
    opposed to the same words in a tool result (a grep of okl's own source, say) or in a message
    another session sent and quoted them in (that starts `<agent-message`, not `Stop hook`)."""
    marker = NOTE.decode()
    kind = d.get("type")
    if kind == "system":
        errors = d.get("hookErrors")
        return isinstance(errors, list) and any(isinstance(e, str) and marker in e for e in errors)
    if kind == "attachment":
        att = d.get("attachment")
        return isinstance(att, dict) and "hook" in str(att.get("type", "")) and marker in json.dumps(att)
    if kind == "user":
        return any(marker in t and t.lstrip().startswith("Stop hook") for t in _user_texts(d))
    return False


def _user_texts(d: dict[str, Any]) -> list[str]:
    """The text a user line carries: its string, or its text blocks; none for a tool result."""
    content = _message(d).get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list) and not any(b.get("type") == "tool_result" for b in _blocks(d)):
        return [str(b.get("text", "")) for b in _blocks(d) if b.get("type") == "text"]
    return []


def _is_human_prompt(d: dict[str, Any]) -> bool:
    """Whether a line is a prompt a person typed. Claude Code 2.1.302 marks one `origin: {"kind":
    "human"}`; a task notification and another session's message carry other kinds, and are not a
    person. An older transcript has no `origin`, and there a user line is a prompt unless it is a tool
    result, marked meta, empty, or a notification, a reminder or hook feedback by its text."""
    if d.get("type") != "user" or d.get("isMeta"):
        return False
    text = " ".join(_user_texts(d)).strip()
    if not text:
        return False
    origin = d.get("origin")
    if origin:
        return isinstance(origin, dict) and origin.get("kind") == "human"
    return not text.startswith(_NOT_A_PROMPT)


class _Main:
    """One pass over the main transcript.

    Before the review starts only two cheap tests run on each line, since a long session's
    transcript is hundreds of megabytes: does it hold the note, and does it hold `--change`. From
    the review's first call to its end every line is read; after its end only the note matters.

    Where the Stop hook asked for the review, it is the first command that ran `okl check --change`
    after the note: one before the note reviewed a different state, so a window opened before the
    note is thrown away, tallies and all. Without a note, the first command that ran it.

    The review ends at the next prompt a person typed, or at a Stop-hook summary with no sub-agent
    the review started still pending. In Claude Code every Agent call returns at once as
    `async_launched` and the agent stops until a task notification names it; the review steps check
    one lesson after another, so the session stops between lessons and the review is not over.
    """

    def __init__(self) -> None:
        self.asked = False           # the note is in the transcript
        self.noted = False           # ... and has been read, so a review from here on follows it
        self._clear()

    def _clear(self) -> None:
        """Start with no review window open."""
        self.started = False
        self.ended = False
        self.after_note = False      # the open window began after the note
        self.start: float | None = None
        self.end_ts: float | None = None
        self.review_id: str | None = None
        self.files: int | None = None
        self.listed: int | None = None
        self.agents: dict[str, dict[str, Any]] = {}     # Agent tool_use id -> its input and result
        self.pending: set[str] = set()                  # Agent calls not yet reported back
        self.awaiting: dict[str, Any] = {}              # a pending call's id -> the agent id it launched
        self.tally = _Tally()

    def feed(self, line: bytes) -> None:
        has_note = NOTE in line
        if self.ended and not has_note:
            return
        if not self.started and not has_note and b"--change" not in line:
            return
        d = _loads(line)
        if d is None:
            return
        if has_note and _carries_note(d):
            self._note()
        if not self.started:
            if self._try_start(d):
                self._event(d)
        elif not self.ended:
            self._step(d)

    def _note(self) -> None:
        """The Stop hook asked for the review. A window open from before it is not that review."""
        self.asked = True
        if self.started and not self.after_note:
            self._clear()
        self.noted = True

    def _step(self, d: dict[str, Any]) -> None:
        """Read one line of an open window, or end it."""
        stopped = d.get("type") == "system" and d.get("subtype") == "stop_hook_summary"
        if _is_human_prompt(d) or (stopped and not self.pending):
            self.ended, self.end_ts = True, _ts(d)
        else:
            self._event(d)

    def _try_start(self, d: dict[str, Any]) -> bool:
        """Start the review at this line if it runs the review; whether it did."""
        for b in _blocks(d):
            inp = b.get("input")
            cmd = inp.get("command") if isinstance(inp, dict) else None
            if (b.get("type") == "tool_use" and b.get("name") == "Bash" and isinstance(cmd, str)
                    and reviewcmd.is_review_command(cmd)):
                self.started, self.start, self.review_id = True, _ts(d), b.get("id")
                self.after_note = self.noted
                return True
        return False

    def _event(self, d: dict[str, Any]) -> None:
        self.tally.add(d)
        blocks = _blocks(d)
        results = [b for b in blocks if b.get("type") == "tool_result"]
        for b in blocks:
            if b.get("type") == "tool_use" and b.get("name") in (SUBAGENT_TOOL, SUBAGENT_TOOL_OLD) \
                    and isinstance(b.get("id"), str) and b["id"] not in self.agents:
                inp = b.get("input")
                self.agents[b["id"]] = {"input": inp if isinstance(inp, dict) else {}}
                self.pending.add(b["id"])
        for b in results:
            # toolUseResult describes the line's one result; with several, it says nothing of which
            self._result(b, d.get("toolUseResult") if len(results) == 1 else None)
        if self.pending and not results and d.get("type") == "user":
            self._notified(" ".join(_user_texts(d)))

    def _result(self, b: dict[str, Any], res: Any) -> None:
        """A tool result: the review's own output, or a sub-agent's launch or completion."""
        tid = b.get("tool_use_id")
        if tid == self.review_id and self.files is None and self.listed is None:
            self._counts(_text(b.get("content")))
        elif tid in self.agents:
            res = res if isinstance(res, dict) else {}
            if res:
                self.agents[tid].update(agent_id=res.get("agentId"), model=res.get("resolvedModel"))
            if res.get("status") == "async_launched" or res.get("isAsync") is True:
                self.awaiting[tid] = res.get("agentId")      # running in the background: wait for its notification
            else:
                self.pending.discard(tid)

    def _notified(self, text: str) -> None:
        """A user line that names a pending sub-agent (a task notification) reports it back."""
        for tid in list(self.pending):
            aid = self.awaiting.get(tid)
            if tid in text or (isinstance(aid, str) and aid in text):
                self.pending.discard(tid)

    def _counts(self, text: str) -> None:
        if (m := _FILES.search(text)):
            self.files = int(m.group(1))
        elif "nothing changed since" in text:
            self.files = 0
        if (m := _LISTED.search(text)):
            self.listed = int(m.group(1))


def read_review(transcript: str | Path, *, repo_dir: str | None = None,
                known_ids: set[str] | None = None) -> ReviewReading:
    """What the session's transcript says about its review after writing; never raises.

    `repo_dir` makes the edited paths and test targets relative to the repository, and is what a
    path must be inside to be kept. `known_ids`, when given, keeps only lesson ids the store has,
    so nothing but a lesson's id reaches a row from a command line.
    """
    path = Path(transcript)
    reading = ReviewReading(session=path.stem)
    try:
        return _read(path, reading, repo_dir, known_ids)
    except Exception:  # noqa: BLE001 - a log of the review must never fail the stop it rides on
        return reading


def _read(path: Path, reading: ReviewReading, repo_dir: str | None,
          known_ids: set[str] | None) -> ReviewReading:
    main = _Main()
    try:
        with path.open("rb") as f:
            for line in f:
                main.feed(line)
    except OSError:
        return reading
    reading.readable, reading.asked, reading.ran = True, main.asked, main.started
    if not main.started:
        return reading
    reading.files_changed, reading.lessons_listed = main.files, main.listed
    tokens, seen_tokens, last = main.tally.tokens, main.tally.seen, main.tally.last
    for check, read in _checks(main, path.parent / path.stem / "subagents", repo_dir, known_ids):
        reading.checks.append(check)
        if read:
            tokens, seen_tokens = tokens + int(check["tokens"]), True
            if read["last"] is not None:
                last = read["last"] if last is None else max(last, read["last"])
    reading.tokens = tokens if seen_tokens else None
    if main.start is not None and last is not None:
        reading.duration_s = max(0, round(last - main.start))
    return reading


def _checks(main: _Main, sub_dir: Path, repo_dir: str | None,
            known_ids: set[str] | None) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Each sub-agent the review started, in order, as the row keeps it with what its transcript held.
    Each is matched to its meta file by the tool call that started it; without one, by the agent id
    the call's own result named."""
    metas = _metas(sub_dir) if main.agents else {}
    out = []
    for tool_id, call in main.agents.items():
        agent_id, meta = metas.get(tool_id, (call.get("agent_id"), {}))
        out.append(_check(sub_dir, agent_id, meta, call, repo_dir=repo_dir, known_ids=known_ids,
                          until=main.end_ts))
    return out


def _check(sub_dir: Path, agent_id: Any, meta: dict[str, Any], call: dict[str, Any], *, repo_dir: str | None,
           known_ids: set[str] | None, until: float | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """One sub-agent the review started, as the row keeps it, and what its transcript held."""
    prompt = call["input"].get("prompt")
    prompt = prompt if isinstance(prompt, str) else ""
    read = None
    if isinstance(agent_id, str) and _AGENT_ID.fullmatch(agent_id):
        read = _read_agent(sub_dir / f"agent-{agent_id}.jsonl", repo_dir, until)
    else:
        agent_id = None
    ids = (read["lessons"] if read else []) + _SHOWN.findall(prompt) + reviewcmd.text_show_ids(prompt)
    lessons = list(dict.fromkeys(i for i in ids if _ID.fullmatch(i) and (known_ids is None or i in known_ids)))
    check: dict[str, Any] = {
        "agent": agent_id,
        # what the sub-agent ran on, as its own transcript says; then what was asked for
        "model": _model(read["model"] if read else None, meta.get("model"), meta.get("pickedEffortModel"),
                        call.get("model"), call["input"].get("model")),
        "lessons": lessons[:MAX_LESSONS],
        "read": read is not None,
        "edited": bool(read and read["edited"]),
        "edited_files": read["edited_files"] if read else [],
        "edited_outside": read["edited_outside"] if read else 0,
        "tests": read["tests"] if read else [],
        "tokens": read["tokens"] if read else None,
    }
    return check, read
