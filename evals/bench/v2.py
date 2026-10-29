"""Prototype of the second-generation briefing decision, measured on the bench before any of it
reaches src/okl (#291). The production path will call the same functions or be measured
against this one; a prototype that drifts from what ships is the defect a generated diagram
once had (generated-diagram-traced-old-path).

The idea, in one line per stage:

1. Gate: a prompt a harness wrote (task notifications, sub-agent reports, system reminders) or
   one with no subject word briefs nothing, decided on the prompt alone.
2. Candidates: okl's full-text search over every field, triggers included (store.search).
3. Score: for each candidate, the share of the prompt's subject that the lesson's "about"
   fields cover (title, symptom, aliases, triggers), each word weighted by its inverse
   document frequency in the store. 1.0 means every subject word, rare ones counting most,
   is in what the lesson says it is about. It is comparable across prompts, so one line
   means the same thing for a two-word prompt and a forty-word one.
4. Decide: brief the candidates at or above a line chosen on the null prompts (conformal:
   the line is the (1 - alpha) quantile of the null prompts' best scores, with the
   finite-sample correction, so at most alpha of new null prompts are briefed anything),
   best first, at most `cap`.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from okl import core
from okl import store as okl_store
from okl.store import Node, Store

# Text a harness wraps around a message it delivers as a user turn. A prompt that starts with
# one was not typed by the person, and briefing it spent up to twelve lessons per sub-agent
# report in the session that found this (2026-10-25).
HARNESS_PREFIXES = ("<task-notification", "<agent-message", "<system-reminder", "<local-command",
                    "<command-name", "<command-message", "<bash-input", "<bash-stdout", "<user-prompt-submit-hook")

# Unicode letters and digits, split as core.briefing_terms splits the task (str.isalnum):
# an ASCII-only pattern cut "café" to "caf", so a task word with an accent never counted
# (review on #292).
_WORD = re.compile(r"[^\W_]+")


def from_harness(task: str) -> bool:
    """Whether a harness, not the person, wrote this prompt."""
    return task.lstrip().startswith(HARNESS_PREFIXES)


# Stemming (REPORT §4ac): off unless an arm turns it on (set_stem). When on, the line's word
# matching stems each word with FTS5's own Porter tokenizer, so it agrees with an index built
# with that tokenizer rather than with a second stemmer's opinion.
STEM = False


def set_stem(on: bool) -> None:
    """Stem the line's words, and build the corpus store's index with the Porter tokenizer, or
    neither. The product stems by default (store.FTS_TOKENIZE, REPORT §4ad), so an unstemmed arm
    has to say so before its store is built."""
    global STEM
    STEM = on
    okl_store.FTS_TOKENIZE = "porter unicode61" if on else "unicode61"
_STEMS: dict[str, str] = {}
_PORTER: sqlite3.Connection | None = None


def stem(word: str) -> str:
    """`word` as FTS5's porter tokenizer indexes it, read back through fts5vocab."""
    global _PORTER
    if word not in _STEMS:
        if _PORTER is None:
            _PORTER = sqlite3.connect(":memory:")
            _PORTER.execute("CREATE VIRTUAL TABLE s USING fts5(x, tokenize='porter unicode61')")
            _PORTER.execute("CREATE VIRTUAL TABLE v USING fts5vocab(s, 'instance')")
        _PORTER.execute("DELETE FROM s")
        _PORTER.execute("INSERT INTO s VALUES (?)", (word,))
        row = _PORTER.execute("SELECT term FROM v ORDER BY offset LIMIT 1").fetchone()
        _STEMS[word] = row[0] if row else word
    return _STEMS[word]


def words(text: str) -> set[str]:
    """Lower-cased runs of Unicode letters and digits, the task's tokenization (core.briefing_terms);
    stemmed when STEM is on."""
    found = set(_WORD.findall(text.lower()))
    return {stem(w) for w in found} if STEM else found


def about_text(n: Node) -> str:
    """What a lesson says it is about: title, symptom, aliases and triggers (not its body)."""
    return " ".join(x or "" for x in (n.title, n.symptom, n.aliases, getattr(n, "triggers", None)))


@dataclass
class Index:
    """Document frequencies over the live records' about-text and full text."""
    n: int
    df: dict[str, int]
    about: dict[str, set[str]]
    full: dict[str, set[str]]

    def idf(self, w: str) -> float:
        """Smoothed inverse document frequency of `w` across the live records."""
        return math.log((self.n + 1) / (self.df.get(w, 0) + 0.5))


def build_index(store: Store) -> Index:
    """Word sets and document frequencies for the store's live records."""
    nodes = [n for n in store.all_nodes() if n.status not in core.RETIRED_STATUSES]
    about = {n.id: words(about_text(n)) for n in nodes}
    full = {n.id: words(" ".join(x or "" for x in (about_text(n), n.body, n.fix))) for n in nodes}
    df: dict[str, int] = {}
    for ws in full.values():
        for w in ws:
            df[w] = df.get(w, 0) + 1
    return Index(len(nodes), df, about, full)


def subject(task: str) -> list[str]:
    """The prompt's subject words, lower-cased: okl's own briefing terms."""
    return [t.lower() for t in core.briefing_terms(task)]


def coverage(index: Index, terms: list[str], node_id: str) -> float:
    """IDF-weighted share of the prompt's subject words that the lesson's about-text holds."""
    if not terms:
        return 0.0
    mass = sum(index.idf(t) for t in terms)
    got = sum(index.idf(t) for t in terms if t in index.about.get(node_id, ()))
    return got / mass if mass else 0.0


def evidence(index: Index, terms: list[str], node_id: str) -> float:
    """Rare-word evidence: the summed IDF of the prompt's subject words the lesson's
    about-text holds. Absolute, so a one-word prompt cannot score like a thirty-word one."""
    return sum(index.idf(t) for t in terms if t in index.about.get(node_id, ()))


def evidence_full(index: Index, terms: list[str], node_id: str) -> float:
    """The same over the lesson's whole text, body and fix included."""
    return sum(index.idf(t) for t in terms if t in index.full.get(node_id, ()))


def shared_words(index: Index, terms: list[str], node_id: str) -> float:
    """How many of the prompt's subject words the about-text holds, ties broken by their
    rarity relative to the store (each word's IDF over the largest a word in the store can
    have), so the tie-break means the same at 30 records and at 30,000."""
    about = index.about.get(node_id, ())
    top = math.log((index.n + 1) / 1.5)
    shared = [t for t in terms if t in about]
    return len(shared) + sum(index.idf(t) / top for t in shared) / 1000


SCORES = {"coverage": coverage, "evidence": evidence, "evidence_full": evidence_full,
          "shared_words": shared_words}


@dataclass
class Decision:
    """What one prompt was briefed, its best candidate's score, and why nothing, when nothing."""

    ids: list[str]            # briefed, best first
    best: float               # the best candidate's score (what the null line is set on)
    reason: str | None = None


def candidates(store: Store, task: str, repo: str, fetch: int = 36) -> tuple[list[str], list[Node]]:
    """The prompt's subject words and the live, in-scope candidates the full-text search finds
    for them, by okl's own scope rule; ([], []) when the prompt is gated."""
    terms = subject(task)
    if from_harness(task) or not terms:
        return [], []
    # The search gets the words as typed (a porter index stems them itself; stemming twice can
    # differ); the scores get them stemmed, once each, to match the stemmed about-text.
    found = store.search(" ".join(terms), limit=fetch)
    if STEM:
        terms = list(dict.fromkeys(stem(t) for t in terms))
    return terms, [n for n in found if n.status not in core.RETIRED_STATUSES
                   and core._in_scope(n, f"repo:{repo}", None)]


def decide(store: Store, index: Index, task: str, *, line: float, cap: int, repo: str = "bench",
           fetch: int = 36, score: Callable[[Index, list[str], str], float] = coverage) -> Decision:
    """Gate, fetch, score and keep the candidates at or above `line`, best first, at most `cap`."""
    if from_harness(task):
        return Decision([], 0.0, "harness")
    terms, live = candidates(store, task, repo, fetch)
    if not terms:
        return Decision([], 0.0, "no subject")
    scored = sorted(((score(index, terms, n.id), i, n.id) for i, n in enumerate(live)),
                    key=lambda t: (-t[0], t[1]))
    best = scored[0][0] if scored else 0.0
    return Decision([nid for s, _i, nid in scored if s >= line][:cap], best)


def conformal_line(null_bests: list[float], alpha: float) -> float:
    """The smallest line that, on exchangeable new null prompts, briefs anything for at most
    alpha of them: just above the ceil((n+1)(1-alpha))-th smallest best score among n null
    prompts (split conformal, the finite-sample correction included)."""
    n = len(null_bests)
    k = math.ceil((n + 1) * (1 - alpha))
    if k > n:
        return float("inf")
    return sorted(null_bests)[k - 1] + 1e-9
