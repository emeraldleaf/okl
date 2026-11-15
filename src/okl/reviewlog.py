"""What a review after writing did in a real session, read from a Claude Code transcript (#464).

okl calls no model. The agent runs the review: it runs `okl check --change`, starts a sub-agent per
lesson, and each sub-agent may edit code. Only the session's transcript sees all of it. Claude Code
saves the main transcript as `<projects dir>/<session>.jsonl`, and each sub-agent as
`<projects dir>/<session>/subagents/agent-<id>.jsonl` with an `agent-<id>.meta.json` beside it that
names the main transcript's tool call that started it (`toolUseId`) and the model.

That format is Claude Code's and undocumented, so every read here fails soft: what cannot be read
is left out, and nothing raises into the Stop hook this rides on. A reading holds ids, paths, counts,
model names and booleans only: no code, no command line and no text from the session.

A row describes one review, the last one the Stop hook asked for. A note asks for one: the first
command that ran `okl check --change` after it and before the next prompt a person typed. A prompt
first means the request was skipped (asked, not ran), and a run after that prompt is nobody's review.
With several notes in one session the last one counts, and the earlier notes and their runs are not
logged. A run before any note keeps the rule it had: the first one, unasked.

The review is a window of the transcript. It opens at that run and ends at the next prompt a person
typed, or at a Stop-hook summary with no sub-agent it started still pending, whichever comes first.
A background sub-agent is pending from its Agent call until a notification reports it finished, in
whichever of the shapes Claude Code writes one in (see `_reported`). Tokens, time and sub-agents are
counted inside the window, and a sub-agent's own lines up to its end: a session that goes on to other
work after its review must not have that work counted as the review's. An Agent call that came back
as an error started no sub-agent: it is no check, and `failed_launches` counts it. Tokens are the
work (input, output, cache creation) and cache reads are kept apart, in the row and in each check.

Claude Code 2.1.302 also writes `api-request-blob` lines that repeat an assistant message's tool
calls after their results. Only assistant and user lines are read for calls, and a call counts once.

Imports only reviewcmd from okl. The import contract in pyproject.toml holds both below the store, so
the parser has no way to reach it.
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
# The bytes that mark a line a person typed, as 2.1.302 writes it, and a user line, in both spellings of JSON.
_HUMAN_KIND = (b'"kind":"human"', b'"kind": "human"')
_USER_TYPE = (b'"type":"user"', b'"type": "user"')
# A notification's `<status>` when the sub-agent is done. The four values every one of about 2,400
# notifications in two real transcripts carried; a task still running is `running`, in a `task_status`
# attachment, and does not report anything.
_TERMINAL = frozenset({"completed", "failed", "killed", "stopped"})
_STATUS = re.compile(r"<status>\s*([^<]*?)\s*</status>")
_TASK_ID = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>")
_TOOL_ID = re.compile(r"<tool-use-id>\s*([^<\s]+)\s*</tool-use-id>")


@dataclass
class ReviewReading:
    """What one transcript says about the session's review after writing."""

    session: str
    readable: bool = False             # the transcript could be opened
    asked: bool = False                # the Stop hook's note is in it
    ran: bool = False                  # the agent ran `okl check --change` itself
    files_changed: int | None = None   # from the review's own output, when readable
    lessons_listed: int | None = None
    tokens: int | None = None          # the work: input, output and cache creation, with its sub-agents'
    cache_read_tokens: int | None = None   # cache reads, apart: the context a call re-reads, at a far lower price
    duration_s: int | None = None
    failed_launches: int = 0           # Agent calls that came back as an error: no check
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
    The work (input, output and cache creation) and the cache reads are kept apart: a session's
    whole context is read from the cache on every call, so the reads dwarf the work and cost far less.
    """

    def __init__(self) -> None:
        self._work: dict[str, int] = {}
        self._cache: dict[str, int] = {}
        self._anonymous = [0, 0]
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
        work = sum(_num(usage.get(k)) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens"))
        cache = _num(usage.get("cache_read_input_tokens"))
        mid = m.get("id")
        if isinstance(mid, str) and mid:
            self._work[mid] = max(self._work.get(mid, 0), work)
            self._cache[mid] = max(self._cache.get(mid, 0), cache)
        else:
            self._anonymous[0] += work
            self._anonymous[1] += cache

    @property
    def tokens(self) -> int:
        return sum(self._work.values()) + self._anonymous[0]

    @property
    def cache_read(self) -> int:
        return sum(self._cache.values()) + self._anonymous[1]


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
                "tests": tests[:MAX_TESTS], "tokens": self.tally.tokens, "cache_read_tokens": self.tally.cache_read,
                "model": self.model,
                "last": self.tally.last}


def _read_agent(path: Path, root: str | None, until: float | None) -> dict[str, Any] | None:
    """One sub-agent's transcript read, up to `until` (the end of the review's window, when it ended);
    None when the file cannot be opened. A sub-agent the review started and later resumed for other
    work has that work after `until`, and it is not the review's. There is no lower bound on its lines:
    an Agent or Task call always starts a fresh sub-agent, and a resume goes through SendMessage, which
    the window never counts as a check."""
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


def _has_tool_result(d: dict[str, Any]) -> bool:
    return any(b.get("type") == "tool_result" for b in _blocks(d))


def _is_human_prompt(d: dict[str, Any], origin_era: bool = False) -> bool:
    """Whether a line is a prompt a person typed. Claude Code 2.1.302 marks one `origin: {"kind":
    "human"}`, even one with no text (an image); a task notification and another session's message
    carry other kinds, and are not a person. A compact summary is not one either. A transcript with no
    `origin` is an older one, and there a user line is a prompt unless it is a tool result, marked meta,
    empty, or a notification, a reminder or hook feedback by its text; but once a transcript has shown
    an `origin` (`origin_era`), a user line without one is not a typed prompt."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isCompactSummary") or _has_tool_result(d):
        return False
    origin = d.get("origin")
    if origin:
        return isinstance(origin, dict) and origin.get("kind") == "human"
    text = " ".join(_user_texts(d)).strip()
    return not origin_era and bool(text) and not text.startswith(_NOT_A_PROMPT)


def _notification_ids(text: str) -> list[str]:
    """The task and tool-use ids of each task notification in `text` that reports a sub-agent done: its
    `<status>` is a terminal one, or it names none. A notification of a task still running does not."""
    ids: list[str] = []
    for chunk in text.split("<task-notification")[1:]:
        status = _STATUS.search(chunk)
        if status and status.group(1).lower() not in _TERMINAL:
            continue
        ids += _TASK_ID.findall(chunk) + _TOOL_ID.findall(chunk)
    return ids


def _reported(d: dict[str, Any]) -> list[str]:
    """The ids a transcript line reports finished. 2.1.302 writes a finished background sub-agent in
    four shapes, counted over two real transcripts (about 160 as user lines, 190 as `queued_command`
    attachments, 1,700 in `queue-operation` lines, and a `task_status` attachment for a task still
    running): a user line that is a task notification or a peer's hand-back, an attachment of type
    `queued_command` with the notification in its `prompt`, one of type `task_status` with a terminal
    status, and a `queue-operation` line with the notification as its `content`. Any other line that
    mentions an id, a user line that merely quotes one included, reports nothing."""
    kind = d.get("type")
    if kind == "user":
        if _has_tool_result(d):
            return []
        origin: dict[str, Any] = d["origin"] if isinstance(d.get("origin"), dict) else {}
        ids = [origin.get("from"), origin.get("senderTaskId")] if origin.get("kind") == "peer" and origin.get("handback") else []
        text = " ".join(_user_texts(d))
        if origin.get("kind") == "task-notification" or "<task-notification" in text:
            ids += _notification_ids(text)
        return [i for i in ids if isinstance(i, str) and i]
    if kind == "attachment":
        att: dict[str, Any] = d["attachment"] if isinstance(d.get("attachment"), dict) else {}
        if att.get("type") == "queued_command" and isinstance(att.get("prompt"), str):
            return _notification_ids(att["prompt"])
        task = att.get("taskId")
        if att.get("type") == "task_status" and isinstance(task, str) and str(att.get("status")).lower() in _TERMINAL:
            return [task]
        return []
    content = d.get("content")
    return _notification_ids(content) if kind == "queue-operation" and isinstance(content, str) else []


class _Main:
    """One pass over the main transcript.

    Before the review starts only a few cheap tests run on each line, since a long session's transcript
    is hundreds of megabytes: does it hold the note, does it hold `--change`, and, once a note is
    waiting for its review, could it be a prompt a person typed. From the review's first call to its
    end every line is read; after its end only a note matters.

    A note's review is the first command that ran `okl check --change` after that note and before the
    next prompt a person typed. A prompt first means the request was skipped, and a run after it is
    nobody's review. With several notes in one session the row describes the last: the earlier notes,
    and any run after them, are thrown away, tallies and all. A run before any note keeps the rule it
    had: the first command that ran it, unasked, until a note says another review was asked for.

    The review ends at the next prompt a person typed, or at a Stop-hook summary with no sub-agent the
    review started still pending. In Claude Code every Agent call returns at once as `async_launched`
    and the agent stops until a notification names the sub-agent; the review steps check one lesson
    after another, so the session stops between lessons and the review is not over. An Agent call
    that came back as an error started nothing: it is no check, and it is counted apart.
    """

    def __init__(self) -> None:
        self.asked = False           # a note is in the transcript
        self.noted = False           # ... so a review counts only for the last note
        self.waiting = False         # the last note's review has not run, and no prompt has skipped it
        self.origin_era = False      # a user line has carried `origin`: no origin is no typed prompt
        self._clear()

    def _clear(self) -> None:
        """Start with no review window open."""
        self.started = False
        self.ended = False
        self.start: float | None = None
        self.end_ts: float | None = None
        self.review_id: str | None = None
        self.files: int | None = None
        self.listed: int | None = None
        self.failed = 0                                 # Agent calls that came back as an error
        self.agents: dict[str, dict[str, Any]] = {}     # Agent tool_use id -> its input and result
        self.pending: set[str] = set()                  # Agent calls not yet reported back
        self.awaiting: dict[str, Any] = {}              # a pending call's id -> the agent id it launched
        self.tally = _Tally()

    def _maybe_prompt(self, line: bytes) -> bool:
        """Whether a line could be a prompt a person typed, by two byte tests that need no parse."""
        if any(p in line for p in _HUMAN_KIND):
            return True
        # No test for a tool result here: a prompt that mentions one would be skipped, and the parsed
        # line says which user lines are results (`_has_tool_result`).
        return not self.origin_era and any(p in line for p in _USER_TYPE)

    def _worth_parsing(self, line: bytes, has_note: bool) -> bool:
        if has_note:
            return True
        if self.started:
            return not self.ended
        return b"--change" in line or (self.waiting and self._maybe_prompt(line))

    def feed(self, line: bytes) -> None:
        if not self.origin_era and any(p in line for p in _HUMAN_KIND):
            self.origin_era = True
        has_note = NOTE in line
        if not self._worth_parsing(line, has_note) or (d := _loads(line)) is None:
            return
        if has_note and _carries_note(d):
            self._note()
        if self.started:
            if not self.ended:
                self._step(d)
        elif self._try_start(d):
            self._event(d)
        elif self.waiting and _is_human_prompt(d, self.origin_era):
            self.waiting = False        # the person typed before the review ran: the request was skipped

    def _note(self) -> None:
        """The Stop hook asked for the review. Whatever ran before, for no note or an earlier one, is not
        this note's review. (The note comes in two lines, the hook's summary and its feedback, before
        anything can run: the second finds nothing to throw away.)"""
        self.asked = True
        self._clear()
        self.noted = self.waiting = True

    def _step(self, d: dict[str, Any]) -> None:
        """Read one line of an open window, or end it."""
        stopped = d.get("type") == "system" and d.get("subtype") == "stop_hook_summary"
        if _is_human_prompt(d, self.origin_era) or (stopped and not self.pending):
            self.ended, self.end_ts = True, _ts(d)
        else:
            self._event(d)

    def _try_start(self, d: dict[str, Any]) -> bool:
        """Start the review at this line if it runs the review, and it is the one to read; whether it did."""
        if self.noted and not self.waiting:
            return False
        for b in _blocks(d):
            inp = b.get("input")
            cmd = inp.get("command") if isinstance(inp, dict) else None
            if (b.get("type") == "tool_use" and b.get("name") == "Bash" and isinstance(cmd, str)
                    and reviewcmd.is_review_command(cmd)):
                self.started, self.start, self.review_id = True, _ts(d), b.get("id")
                self.waiting = False
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
        if self.pending:
            self._release(_reported(d))

    def _result(self, b: dict[str, Any], res: Any) -> None:
        """A tool result: the review's own output, or a sub-agent's launch, completion or failure."""
        tid = b.get("tool_use_id")
        if tid == self.review_id:
            if b.get("is_error"):
                # The command was refused, or okl could not run it: no review ran. This window closes,
                # and a note's request stays open for a run that does (CodeRabbit, the 0.18.0 sweep).
                noted = self.noted
                self._clear()
                self.waiting = noted
            elif self.files is None and self.listed is None:
                self._counts(_text(b.get("content")))
        elif tid in self.agents:
            if b.get("is_error"):
                del self.agents[tid]            # the call started no sub-agent
                self.pending.discard(tid)
                self.failed += 1
                return
            res = res if isinstance(res, dict) else {}
            if res:
                self.agents[tid].update(agent_id=res.get("agentId"), model=res.get("resolvedModel"))
            if res.get("status") == "async_launched" or res.get("isAsync") is True:
                self.awaiting[tid] = res.get("agentId")      # running in the background: wait for its notification
            else:
                self.pending.discard(tid)

    def _release(self, ids: list[str]) -> None:
        """A pending sub-agent is done when its tool call's id, or the agent's own, is reported."""
        for tid in list(self.pending):
            if tid in ids or self.awaiting.get(tid) in ids:
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
    reading.failed_launches = main.failed
    tokens, cache, seen_tokens, last = main.tally.tokens, main.tally.cache_read, main.tally.seen, main.tally.last
    for check, read in _checks(main, path.parent / path.stem / "subagents", repo_dir, known_ids):
        reading.checks.append(check)
        if read:
            tokens, cache, seen_tokens = tokens + int(check["tokens"]), cache + int(check["cache_read_tokens"]), True
            if read["last"] is not None:
                last = read["last"] if last is None else max(last, read["last"])
    reading.tokens, reading.cache_read_tokens = (tokens, cache) if seen_tokens else (None, None)
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
        "cache_read_tokens": read["cache_read_tokens"] if read else None,
    }
    return check, read
