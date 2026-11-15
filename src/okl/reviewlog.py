"""What a review after writing did in a real session, read from a Claude Code transcript (#464).

okl calls no model. The agent runs the review: it runs `okl check --change`, starts a sub-agent per
lesson, and each sub-agent may edit code. Only the session's transcript sees all of it. Claude Code
saves the main transcript as `<projects dir>/<session>.jsonl`, and each sub-agent as
`<projects dir>/<session>/subagents/agent-<id>.jsonl` with an `agent-<id>.meta.json` beside it that
names the main transcript's tool call that started it (`toolUseId`) and the model.

That format is Claude Code's and undocumented, so every read here fails soft: what cannot be read
is left out, and nothing raises into the Stop hook this rides on. A reading holds ids, paths, counts,
model names and booleans only: no code and no text from the session.

Imports nothing from okl, so the parser has no way to reach the store.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

NOTE = b"REVIEW AFTER WRITING"        # what the Stop hook's one-line note starts with (core.REVIEW_NOTE)
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
# The call that starts a sub-agent. Claude Code renamed it, so a transcript holds one or the other. Two
# names, not a collection: evals/review_e2e.py, a measurement script kept as it ran, writes the same
# pair out, and tests/test_single_source.py fails on a second copy of a collection.
SUBAGENT_TOOL, SUBAGENT_TOOL_OLD = "Agent", "Task"
# Sanity limits on one sub-agent's lists, so a runaway session cannot grow a row without end.
MAX_LESSONS, MAX_FILES, MAX_TESTS, MAX_TARGETS = 100, 100, 50, 6

_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:@+/-]{0,199}")
_AGENT_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_MODEL = re.compile(r"[\w.:/\[\]-]{1,80}")
_SHOW = re.compile(r"\bokl\b\s+show\b([^;&|\n]*)", re.I)
# `okl show` prints `[<id>] Rule · org · created ...` first; a lesson pasted into a prompt keeps it.
_SHOWN = re.compile(r"^\[([^\]\s]+)\] \w+ · ", re.M)
_FILES = re.compile(r"(\d+) file\(s\) changed since")
_LISTED = re.compile(r"This review lists (\d+) lesson\(s\)")
_NOT_RUNNERS = frozenset({"grep", "egrep", "fgrep", "rg", "ack", "cat", "less", "more", "head", "tail",
                          "sed", "awk", "ls", "echo", "printf", "git", "find", "wc", "which", "type",
                          "pip", "pip3", "man", "vim", "nano", "diff", "cp", "mv", "rm", "touch"})
_RUNNER = re.compile(
    r"(?<![\w-])(pytest|py\.test|unittest|tox|nox|jest|vitest|mocha|rspec|phpunit|ctest"
    r"|(?:npm|yarn|pnpm|bun)(?:\s+run)?\s+test|go\s+test|cargo\s+(?:nextest\s+run|test)"
    r"|dotnet\s+test|mvn(?:\s+-\S+)*\s+test|gradlew?\s+test|make\s+test|swift\s+test)(?![\w.-])")
_TARGET = re.compile(r"[\w@.+-]+/(?:[\w@.+-]+/?)*|[\w.-]+\.(?:py|js|jsx|ts|tsx|mjs|rb|go|rs|cs|java|php|sh|swift)")
_FAILED = re.compile(r"\b[1-9]\d* (?:failed|failures?|errors?)\b|\bFAILED\b", re.I)
_PASSED = re.compile(r"\b\d+ passed\b|\bOK\b|\bPASS(?:ED)?\b|\ball tests passed\b", re.I)


@dataclass
class ReviewReading:
    """What one transcript says about the session's review after writing."""

    session: str
    readable: bool = False             # the transcript could be opened
    asked: bool = False                # the Stop hook's note is in it
    ran: bool = False                  # the agent ran `okl check --change` itself
    files_changed: int | None = None   # from the review's own output, when readable
    lessons_listed: int | None = None
    tokens: int | None = None          # the review's, with its sub-agents', from the first call on
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
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _message(d: dict[str, Any]) -> dict[str, Any]:
    m = d.get("message")
    return m if isinstance(m, dict) else {}


def _blocks(d: dict[str, Any]) -> list[dict[str, Any]]:
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


class _Tally:
    """The tokens and the time span of a run of transcript lines.

    Claude Code writes one line per content block of an assistant message, each carrying the
    message's usage, so a message is counted once, by its id, at the largest figure logged for it.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, int] = {}
        self._anonymous = 0
        self.seen = False
        self.first: float | None = None
        self.last: float | None = None

    def add(self, d: dict[str, Any]) -> None:
        ts = _ts(d)
        if ts is not None:
            self.first = ts if self.first is None else min(self.first, ts)
            self.last = ts if self.last is None else max(self.last, ts)
        m = _message(d)
        usage = m.get("usage")
        if not isinstance(usage, dict):
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


# --- what a command line means ---------------------------------------------------------------------

def is_review_command(command: str) -> bool:
    """Whether a Bash command runs the review: `okl check --change`, however okl is reached, but
    not the Stop hook's own `--format hook` note."""
    for seg in re.split(r"[;&|\n]+", command):
        if (re.search(r"\bokl\b", seg, re.I) and re.search(r"\bcheck\b", seg)
                and re.search(r"\s--change\b", seg) and not re.search(r"--format[ =]\s*hook\b", seg)):
            return True
    return False


def show_ids(text: str) -> list[str]:
    """The lesson ids `okl show <id>` names in `text`, in order; flags are skipped."""
    ids = []
    for m in _SHOW.finditer(text):
        toks = m.group(1).split()
        i = 0
        while i < len(toks):
            if toks[i] == "--format":
                i += 2
            elif toks[i].startswith("-"):
                i += 1
            else:
                ids.append(toks[i].strip("\"'`"))
                break
    return ids


def parse_test_run(command: str) -> tuple[str, list[str]] | None:
    """The test runner a Bash command starts and the paths it names, or None. A search or print
    command that only mentions a runner (`grep pytest`) is not a run."""
    for seg in re.split(r"[;&|\n]+", command):
        words = seg.split()
        while words and re.fullmatch(r"\w+=\S*", words[0]):   # FOO=1 pytest: the variable is not the command
            words.pop(0)
        if not words or words[0] in _NOT_RUNNERS:
            continue
        m = _RUNNER.search(seg)
        if not m:
            continue
        targets: list[str] = []
        for tok in seg[m.end():].split():
            t = tok.strip("\"'`").split("::")[0]
            if _TARGET.fullmatch(t) and t not in targets:
                targets.append(t[:200])
        return " ".join(m.group(1).split()), targets[:MAX_TARGETS]
    return None


def parse_test_outcome(is_error: bool, text: str) -> str:
    """"passed", "failed" or "unknown", from what a test command's result says."""
    if text.lstrip().startswith("<tool_use_error>"):
        return "unknown"       # the tool refused; no test ran
    if is_error or _FAILED.search(text):
        return "failed"
    return "passed" if _PASSED.search(text) else "unknown"


def _rel(path: str, root: str | None) -> str:
    """`path` relative to the repository when it is inside it."""
    if root:
        base = root.rstrip(os.sep) + os.sep
        if path.startswith(base):
            return path[len(base):]
    return path


def _valid_id(i: str) -> bool:
    return bool(_ID.fullmatch(i))


# --- the sub-agents ----------------------------------------------------------------------------------

class _AgentScan:
    """What one sub-agent's transcript shows: the lessons it was given or opened, what it edited,
    the tests it ran, its model and its tokens."""

    def __init__(self, root: str | None) -> None:
        self.root = root
        self.lessons: list[str] = []
        self.edited: set[str] = set()
        self.tests: list[dict[str, Any]] = []
        self.model = ""
        self.tally = _Tally()
        self._edits: dict[str, str] = {}                        # an edit call's id -> its path
        self._runs: dict[str, tuple[str, list[str]]] = {}       # a test call's id -> runner, targets

    def feed(self, d: dict[str, Any]) -> None:
        """Fold one transcript line in."""
        self.tally.add(d)
        self.model = self.model or _model(_message(d).get("model"))
        for b in _blocks(d):
            if b.get("type") == "tool_use":
                self._call(b)
            elif b.get("type") == "tool_result":
                self._result(b)

    def _call(self, b: dict[str, Any]) -> None:
        name, tid, inp = str(b.get("name", "")), b.get("id"), b.get("input")
        inp = inp if isinstance(inp, dict) else {}
        if name in EDIT_TOOLS:
            path = inp.get("file_path") or inp.get("notebook_path")
            if isinstance(path, str) and path and isinstance(tid, str):
                self._edits[tid] = _rel(path, self.root)
        elif name == "Bash" and isinstance(inp.get("command"), str):
            self.lessons += show_ids(inp["command"])
            run = parse_test_run(inp["command"])
            if run and isinstance(tid, str):
                self._runs[tid] = run
        elif name.endswith("okl_get") and isinstance(inp.get("id"), str):
            self.lessons.append(inp["id"])

    def _result(self, b: dict[str, Any]) -> None:
        rid = b.get("tool_use_id")
        if rid in self._edits:
            path = self._edits.pop(rid)
            if not b.get("is_error"):       # an edit the tool refused changed nothing
                self.edited.add(path)
        if rid in self._runs:
            runner, targets = self._runs.pop(rid)
            self.tests.append({"runner": runner, "targets": targets, "outcome":
                               parse_test_outcome(bool(b.get("is_error")), _text(b.get("content")))})

    def finish(self) -> dict[str, Any]:
        """The reading. A call with no result in the file reported no error, so an edit counts."""
        edited = self.edited | set(self._edits.values())
        tests = self.tests + [{"runner": r, "targets": t, "outcome": "unknown"}
                              for r, t in self._runs.values()]
        return {"lessons": self.lessons, "edited_files": sorted(edited)[:MAX_FILES],
                "edited": bool(edited), "tests": tests[:MAX_TESTS], "tokens": self.tally.tokens,
                "model": self.model, "last": self.tally.last}


def _read_agent(path: Path, root: str | None) -> dict[str, Any] | None:
    """One sub-agent's transcript read; None when the file cannot be opened."""
    scan = _AgentScan(root)
    try:
        with path.open("rb") as f:
            for line in f:
                d = _loads(line)
                if d is not None:
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


def _model(*candidates: Any) -> str:
    return next((c for c in candidates if isinstance(c, str) and _MODEL.fullmatch(c)), "")


# --- the main transcript -----------------------------------------------------------------------------

class _Main:
    """One pass over the main transcript.

    Before the review starts only two cheap tests run on each line, since a long session's
    transcript is hundreds of megabytes: does it hold the note, and does it hold `--change`. From
    the review's first call on every line is read, which is a short tail.
    """

    def __init__(self) -> None:
        self.asked = False
        self.started = False
        self.start: float | None = None
        self.review_id: str | None = None
        self.files: int | None = None
        self.listed: int | None = None
        self.agents: dict[str, dict[str, Any]] = {}     # Agent tool_use id -> its input and result
        self.tally = _Tally()

    def feed(self, line: bytes) -> None:
        has_note = NOTE in line
        if not self.started and not has_note and b"--change" not in line:
            return
        d = _loads(line)
        if d is None:
            return
        if has_note and _carries_note(d):
            self.asked = True
        if not self.started:
            self._try_start(d)
        if self.started:
            self._event(d)

    def _try_start(self, d: dict[str, Any]) -> None:
        for b in _blocks(d):
            inp = b.get("input")
            cmd = inp.get("command") if isinstance(inp, dict) else None
            if (b.get("type") == "tool_use" and b.get("name") == "Bash" and isinstance(cmd, str)
                    and is_review_command(cmd)):
                self.started, self.start, self.review_id = True, _ts(d), b.get("id")
                return

    def _event(self, d: dict[str, Any]) -> None:
        self.tally.add(d)
        blocks = _blocks(d)
        results = [b for b in blocks if b.get("type") == "tool_result"]
        for b in blocks:
            if b.get("type") == "tool_use" and b.get("name") in (SUBAGENT_TOOL, SUBAGENT_TOOL_OLD) \
                    and isinstance(b.get("id"), str) and b["id"] not in self.agents:
                inp = b.get("input")
                self.agents[b["id"]] = {"input": inp if isinstance(inp, dict) else {}}
        for b in results:
            tid = b.get("tool_use_id")
            if tid == self.review_id and self.files is None and self.listed is None:
                self._counts(_text(b.get("content")))
            elif tid in self.agents and len(results) == 1:
                # toolUseResult describes the line's one result; with several, it says nothing of which
                res = d.get("toolUseResult")
                if isinstance(res, dict):
                    self.agents[tid].update(agent_id=res.get("agentId"), model=res.get("resolvedModel"))

    def _counts(self, text: str) -> None:
        if (m := _FILES.search(text)):
            self.files = int(m.group(1))
        elif "nothing changed since" in text:
            self.files = 0
        if (m := _LISTED.search(text)):
            self.listed = int(m.group(1))


def _carries_note(d: dict[str, Any]) -> bool:
    """Whether a transcript line is the Stop hook's feedback with the review note in it, as
    opposed to the same words in a tool result (a grep of okl's own source, say)."""
    marker = NOTE.decode()
    kind = d.get("type")
    if kind == "system":
        errors = d.get("hookErrors")
        return isinstance(errors, list) and any(isinstance(e, str) and marker in e for e in errors)
    if kind == "attachment":
        att = d.get("attachment")
        return isinstance(att, dict) and "hook" in str(att.get("type", "")) and marker in json.dumps(att)
    if kind == "user":
        content = _message(d).get("content")
        texts = ([content] if isinstance(content, str) else
                 [b.get("text") for b in _blocks(d) if b.get("type") == "text"])
        return any(isinstance(t, str) and marker in t and ("Stop hook" in t or "stop-okl-encode" in t)
                   for t in texts)
    return False


def read_review(transcript: str | Path, *, repo_dir: str | None = None,
                known_ids: set[str] | None = None) -> ReviewReading:
    """What the session's transcript says about its review after writing; never raises.

    `repo_dir` makes the edited paths relative to the repository. `known_ids`, when given, keeps
    only lesson ids the store has, so nothing but a lesson's id reaches a row from a command line.
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
    tokens = main.tally.tokens
    seen_tokens, last = main.tally.seen, main.tally.last
    sub_dir = path.parent / path.stem / "subagents"
    metas = _metas(sub_dir) if main.agents else {}
    for tool_id, call in main.agents.items():
        agent_id, meta = metas.get(tool_id, (call.get("agent_id"), {}))
        check, read = _check(sub_dir, agent_id, meta, call, repo_dir=repo_dir, known_ids=known_ids)
        reading.checks.append(check)
        if read:
            tokens, seen_tokens = tokens + int(check["tokens"]), True
            if read["last"] is not None:
                last = read["last"] if last is None else max(last, read["last"])
    reading.tokens = tokens if seen_tokens else None
    if main.start is not None and last is not None:
        reading.duration_s = max(0, round(last - main.start))
    return reading


def _check(sub_dir: Path, agent_id: Any, meta: dict[str, Any], call: dict[str, Any], *,
           repo_dir: str | None, known_ids: set[str] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """One sub-agent the review started, as the row keeps it, and what its transcript held."""
    prompt = call["input"].get("prompt")
    prompt = prompt if isinstance(prompt, str) else ""
    read = None
    if isinstance(agent_id, str) and _AGENT_ID.fullmatch(agent_id):
        read = _read_agent(sub_dir / f"agent-{agent_id}.jsonl", repo_dir)
    else:
        agent_id = None
    ids = (read["lessons"] if read else []) + _SHOWN.findall(prompt) + show_ids(prompt)
    lessons = list(dict.fromkeys(i for i in ids if _valid_id(i) and (known_ids is None or i in known_ids)))
    check: dict[str, Any] = {
        "agent": agent_id,
        "model": _model(meta.get("model"), meta.get("pickedEffortModel"), call.get("model"),
                        read["model"] if read else None, call["input"].get("model")),
        "lessons": lessons[:MAX_LESSONS],
        "read": read is not None,
        "edited": bool(read and read["edited"]),
        "edited_files": read["edited_files"] if read else [],
        "tests": read["tests"] if read else [],
        "tokens": read["tokens"] if read else None,
    }
    return check, read
