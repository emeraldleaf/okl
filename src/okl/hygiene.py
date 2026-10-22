"""Hygiene detectors for lessons: trace-shaped and over-scoped records (#252, #255).

Pure functions over a record's text, shared by `okl metric` (which reports rates) and
`okl seed` (which warns, or fails under --strict). Both read the same signals, so the
two never disagree about a record.

Why these two shapes: the research on memory transfer finds that abstract lessons and
validation routines carry across codebases while raw traces cause negative transfer
through excessive specificity (docs/RELATED-WORK.md). A pack row is meant to be a Rule,
a Decision, a Gate or a Defect with its cause, never a transcript of how it was found,
and an org lesson that names one repository's paths is the kind that transfers badly.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# A record is trace-shaped when its prose carries pasted artefacts, or simply too much.
_DIFF_LINE = re.compile(r"^(diff --git |\+\+\+ |--- |@@ )", re.MULTILINE)
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)|^\s*File \".+\", line \d+", re.MULTILINE)
_SHELL_PROMPT = re.compile(r"^\$ \S", re.MULTILINE)
LONG_PROSE_CHARS = 1800   # generous: a long but prose-shaped record passes
MANY_LINES = 12

# An org record is over-scoped when its subject fields name one repository's world.
_ABS_PATH = re.compile(r"(?:(?<=\s)|^)(?:/(?:Users|home|var|opt|tmp|srv|mnt)/\S+|[A-Za-z]:\\\S+)")
_DEEP_PATH = re.compile(r"(?<![\w/])[\w.-]+(?:/[\w.-]+){2,}\.\w{1,6}\b")


def _field(rec: Any, name: str) -> str:
    """A text field of a record, whether it is a Node or the dict form a seed file holds."""
    value = rec.get(name) if isinstance(rec, dict) else getattr(rec, name, None)
    return value or ""


def trace_signals(rec: Any) -> list[str]:
    """Why a record looks like a pasted trace rather than a lesson; [] when it does not."""
    prose = "\n".join(_field(rec, f) for f in ("body", "symptom", "fix"))
    out = []
    if _DIFF_LINE.search(prose):
        out.append("diff markers")
    if _TRACEBACK.search(prose):
        out.append("stack-trace lines")
    if _SHELL_PROMPT.search(prose):
        out.append("shell prompt lines")
    if len(prose) > LONG_PROSE_CHARS:
        out.append(f"over {LONG_PROSE_CHARS} characters of prose")
    if prose.count("\n") + 1 > MANY_LINES:
        out.append(f"over {MANY_LINES} lines")
    return out


def overscope_signals(rec: Any, repo_names: Iterable[str] = ()) -> list[str]:
    """Why an org record names one repository's world in its subject fields; [] when not.

    Reads title, symptom and fix, the fields that say what a lesson is about and what to
    do. The body is left alone: it is the cause, and may legitimately say where the
    lesson was paid for. `repo_names` are the repositories the store knows.
    """
    if _field(rec, "scope") != "org":
        return []
    subject = " ".join(_field(rec, f) for f in ("title", "symptom", "fix"))
    out = []
    if _ABS_PATH.search(subject):
        out.append("an absolute path")
    if _DEEP_PATH.search(subject):
        out.append("a repository-deep file path")
    low = subject.lower()
    named = sorted(r for r in {n.strip().lower() for n in repo_names if n}
                   if r not in ("unknown", "") and re.search(r"(?<![\w-])" + re.escape(r) + r"(?![\w-])", low))
    if named:
        out.append("a repository's name: " + ", ".join(named))
    return out


def hygiene_warnings(records: Iterable[Any], repo_names: Iterable[str] = ()) -> list[str]:
    """One line per flagged record, for `okl seed` and the metric's listings."""
    names = list(repo_names)
    lines = []
    for rec in records:
        ident = _field(rec, "id") or _field(rec, "key") or _field(rec, "title")[:48]
        trace = trace_signals(rec)
        over = overscope_signals(rec, names)
        if trace:
            lines.append(f"{ident}: trace-shaped ({'; '.join(trace)}) — a lesson is a rule, a "
                         "decision or a defect with its cause, not a transcript; traces transfer badly")
        if over:
            lines.append(f"{ident}: over-scoped org record ({'; '.join(over)}) — an org lesson "
                         "that names one repository's world is the kind that transfers badly")
    return lines
