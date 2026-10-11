"""What a session touched: the lessons it was briefed on, and those whose files it changed.

The Stop question asked once, generically, whether a session learned anything. It told the
agent how to update or retire a lesson, never which ones to look at, so the loop only added
(okl review R4). This names them, so the agent can say which were wrong, out of date or
replaced, and propose the change to the person.

The briefed lessons come from the session's transcript, where Claude Code records each
UserPromptSubmit hook's context. That format is Claude Code's and undocumented, so every
read here fails soft: a transcript it cannot parse yields no lessons, never an error.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .drift import SNAPSHOT_FILE, _glob_matches
from .store import RETIRED_STATUSES, Node

# A briefed lesson's id follows its bold title: `- **FIX: title** [id]` (R1).
_ID = re.compile(r"\*\* \[([^\]\s]+)\]")
# Claude Code keeps a long hook context in a file and leaves a preview in the transcript.
_SAVED = re.compile(r"Full output saved to: (\S+)")
_MAX_SAVED_BYTES = 1_000_000


def _hook_context(line: bytes) -> list[str]:
    """The text a UserPromptSubmit hook added to the context, from one transcript line."""
    # Cheap filter first: a long session's transcript runs to hundreds of megabytes.
    if b"hook_additional_context" not in line:
        return []
    try:
        att = json.loads(line).get("attachment") or {}
    except (ValueError, AttributeError):
        return []
    if att.get("type") != "hook_additional_context" or att.get("hookEvent") != "UserPromptSubmit":
        return []
    content = att.get("content")
    return [c for c in (content if isinstance(content, list) else [content]) if isinstance(c, str)]


def _full_text(text: str) -> str:
    """The whole briefing when the transcript holds only a preview of it."""
    m = _SAVED.search(text)
    if not m:
        return text
    try:
        p = Path(m.group(1))
        if p.is_file() and p.stat().st_size <= _MAX_SAVED_BYTES:
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return text


def briefed_ids(transcript: str | Path) -> Counter[str]:
    """How many times each lesson id was briefed to the agent in this session.

    Only okl's own briefings count, and only as the prompt hook injected them: the same
    text in a tool result (an `okl check` the agent ran) was output it read, not a briefing.
    """
    counts: Counter[str] = Counter()
    try:
        with Path(transcript).open("rb") as f:
            for line in f:
                for text in _hook_context(line):
                    if "OKL briefing" in text:
                        counts.update(dict.fromkeys(_ID.findall(_full_text(text)), 1))
    except OSError:
        return Counter()
    return counts


def session_start(transcript: str | Path) -> str | None:
    """The first timestamp in the transcript: when the session began, as ISO 8601."""
    try:
        with Path(transcript).open("rb") as f:
            for line in f:
                try:
                    ts = json.loads(line).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if isinstance(ts, str) and ts:
                    return ts
    except OSError:
        pass
    return None


def _git_lines(repo_dir: str, *args: str) -> list[str]:
    try:
        r = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return r.stdout.splitlines() if r.returncode == 0 else []


def changed_paths(repo_dir: str, since: str | None) -> set[str]:
    """Paths this session changed: uncommitted edits, and files in commits since `since`.

    okl's own snapshot and store are left out; verify rewrites the snapshot on its own.
    """
    paths = set()
    for line in _git_lines(repo_dir, "status", "--porcelain", "--untracked-files=all", "--",
                           ".", f":(exclude){SNAPSHOT_FILE}", ":(exclude).okl"):
        path = line[3:]
        paths.add(path.split(" -> ", 1)[-1].strip('"'))    # a rename: the new path
    if since:
        paths.update(p for p in _git_lines(repo_dir, "log", f"--since={since}", "--name-only",
                                           "--format=") if p)
    return paths


def governing(nodes: list[Node], repo: str, paths: set[str]) -> list[Node]:
    """Live lessons in this repo's view whose governed files include one of `paths`."""
    repo_scope = f"repo:{repo}"
    out = []
    for n in nodes:
        if not n.files or n.status in RETIRED_STATUSES or n.scope not in ("org", repo_scope):
            continue
        globs = [g for g in n.files.split(",") if g.strip()]
        if any(_glob_matches(g, p) for g in globs for p in paths):
            out.append(n)
    return out


def recap(nodes: list[Node], repo: str, repo_dir: str, transcript: str | None, *,
          since: str | None = None, limit: int = 5) -> dict[str, Any]:
    """The lessons to put to the agent at the end of a session.

    `briefed`: (lesson, times briefed), most often first, live lessons only, at most
    `limit`. `changed`: live lessons whose governed files the session changed, at most
    `limit`, with `changed_more` counting the rest.
    """
    by_id = {n.id: n for n in nodes}
    counts = briefed_ids(transcript) if transcript else Counter()
    briefed = [(by_id[i], c) for i, c in counts.most_common()
               if i in by_id and by_id[i].status not in RETIRED_STATUSES][:limit]
    start = since or (session_start(transcript) if transcript else None)
    changed = governing(nodes, repo, changed_paths(repo_dir, start)) if (start or transcript) else []
    # Capped too: a session that ran for days changes most of a repo.
    return {"briefed": briefed, "changed": changed[:limit],
            "changed_more": max(0, len(changed) - limit)}


def render(result: dict[str, Any]) -> str:
    """The recap as the Stop question shows it, or "" when the session touched no lesson."""
    briefed, changed = result["briefed"], result["changed"]
    if not briefed and not changed:
        return ""
    out = []
    if briefed:
        out.append("\nLessons this session was briefed on, most often first. Is any of them "
                   "wrong, out of date, or replaced by a better one?")
        out += [f"  [{n.id}] {n.title} ({c}×)" for n, c in briefed]
    if changed:
        out.append("\nLessons whose governed files this session changed. Are they still true?")
        out += [f"  [{n.id}] {n.title} (governs {n.files})" for n in changed]
        if result.get("changed_more"):
            out.append(f"  and {result['changed_more']} more: `okl drift` lists every lesson "
                       "whose files changed since its check")
    out += ["\nIf one needs a change, propose it to the person in one line, and make it only "
            "once they agree:",
            "  wrong or replaced: okl retire <id> --reason \"...\" [--by <new-id>]",
            "  needs correcting:  okl update <id> --fix \"...\"   (keeps its proof)",
            "  still true after the change: okl verify <id>, or okl reverify for all of them",
            "  briefed but irrelevant to this work: say which, in one line. That is noise in "
            "the briefing, not a reason to retire the lesson.",
            "If none needs anything, say so in one line."]
    return "\n".join(out) + "\n"
