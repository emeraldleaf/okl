"""The calibrated briefing decision: which candidates a prompt is briefed, or none (#291).

The full-text search finds candidates; this decides. It replaces the word floor (REPORT §4n,
§4v) when `decision` is "calibrated", the default (DEFAULT), and it answers three questions in
order:

1. Did a person write this prompt? A message a harness delivers as a user turn (a task
   notification, a sub-agent's report, a system reminder) is briefed nothing. Briefing them
   spent up to twelve lessons per sub-agent report in the session that found it (2026-10-25).
2. Does it name a subject? No subject word, nothing (core.briefing_terms decides).
3. Which candidates say they are about this subject? A lesson's about-text is its title,
   symptom, aliases and triggers, what it says it is about and when it applies, not its body.
   Its score is how many of the prompt's subject words that text holds, ties broken by how
   rare those words are in the store: each word's inverse document frequency over the largest
   a word in this store can have (a word in one record), summed, divided by a thousand so it
   never outweighs a whole word. Relative, so the tie-break means the same at thirty records
   and at thirty thousand; an absolute IDF sum would let two rare words through on a big
   store and never on a small one (found by the suite's 32-record test). A candidate is
   briefed at or above CALIBRATED_LINE, best first, at most CALIBRATED_CAP of them.

Why this score: on the retrieval bench (evals/bench/, REPORT §4w) the share-of-subject score
saturated on one-word prompts (a lone "merge" covered by a title scored 1.0, like a thirty-word
bug report), and absolute evidence without triggers abstained on two lessons in three. With
triggers (write-time phrasings of the moments a lesson applies) the shared-word count
separated a query's governing lesson from the best candidate of a real subjectless prompt at
AUC 0.96 on the selection split.

Why this line: it is the split-conformal line at alpha 0.05 over half the bench's 550 real
null prompts (prompts a person typed that name no subject of their own): at most 5 per cent
of such prompts, exchangeable with those, are briefed anything. In words, a lesson is briefed
when what it says it is about holds four of the prompt's subject words, or three whose relative
rarities sum past 1.449. Words are matched by stem (§4ac, §4ad): "rotating" and "rotate" are one
word, which lets more words match on both sides and raised the line from two words to three. It
was measured on one developer's prompts; a store calibrates its own line on its own prompts with
the same procedure (the guarantee is per population).
"""
from __future__ import annotations

import contextlib
import math
import re
import sqlite3
from collections.abc import Iterable
from typing import Final

from . import store
from .store import Node

# The bench's conformal line (evals/bench/, REPORT §4w) with stemmed words (§4ac, §4ad): the
# 269th of 282 calibration nulls' best scores, 3.0014485960, and just above it (tests/test_warm.py
# reads it from the receipt). Unstemmed, it was 2.0017173.
CALIBRATED_LINE = 3.0014486
CALIBRATED_CAP = 5

# Text a harness wraps around a message it delivers as a user turn. Claude Code's task and
# sub-agent notifications and system reminders reach the prompt hook this way.
HARNESS_PREFIXES = ("<task-notification", "<agent-message", "<system-reminder", "<local-command",
                    "<command-name", "<command-message", "<bash-input", "<bash-stdout",
                    "<user-prompt-submit-hook")

# Unicode letters and digits, split as core.briefing_terms splits the task (str.isalnum):
# an ASCII-only pattern cut "café" to "caf", so a task word with an accent never counted
# (review on #292).
_WORD = re.compile(r"[^\W_]+")


SETTINGS = ("floor", "calibrated", "tiered")
# "tiered" shows what clears the calibrated line in full and lists everything else that
# matched, one line each, so a lesson the line misses is still named (REPORT §4y). On real
# prompts "calibrated" alone reached 38 of the 101 applying lessons the floor's 90 came from
# (§4x); "floor" shows all of its matches in full, about 7.7 a prompt.
DEFAULT: Final = "tiered"


def check_setting(decision: str) -> None:
    """Refuse a decision setting okl does not have, naming the ones it does."""
    if decision not in SETTINGS:
        raise ValueError(f"decision must be one of {', '.join(SETTINGS)}, not {decision!r}")


def from_harness(task: str) -> bool:
    """Whether a harness, not the person, wrote this prompt."""
    return task.lstrip().startswith(HARNESS_PREFIXES)


def stemmed() -> bool:
    """Whether the line's words are stemmed: whenever the full-text index stems them
    (store.FTS_TOKENIZE), so a lesson the search found by another form of a word scores it too."""
    return store.FTS_TOKENIZE.split()[0] == "porter"


_STEMS: dict[str, str] = {}


def stems(found: Iterable[str]) -> dict[str, str]:
    """Each word as FTS5's porter tokenizer indexes it, read back through fts5vocab, so the line
    and the index agree on what a word is rather than a second stemmer having its own opinion;
    the word itself where this Python's SQLite has no FTS5. Cached for the process, with every
    word not yet seen stemmed in one pass: a check stems every word of the store's records."""
    todo = [w for w in dict.fromkeys(found) if w not in _STEMS]
    if todo:
        got: dict[int, str] = {}
        with contextlib.suppress(sqlite3.OperationalError), contextlib.closing(sqlite3.connect(":memory:")) as c:
            c.execute("CREATE VIRTUAL TABLE s USING fts5(x, tokenize='porter unicode61')")
            c.execute("CREATE VIRTUAL TABLE v USING fts5vocab(s, 'instance')")
            # Every word in one row, read back in order: under half the time of a row each. A
            # word is letters and digits, so one token; if a tokenizer ever split one, the count
            # would differ and each word gets its own row.
            c.execute("INSERT INTO s(rowid, x) VALUES (0, ?)", (" ".join(todo),))
            terms = [t for (t,) in c.execute("SELECT term FROM v WHERE doc = 0 ORDER BY offset")]
            if len(terms) == len(todo):
                got = dict(enumerate(terms, 1))
            else:
                c.executemany("INSERT INTO s(rowid, x) VALUES (?, ?)", enumerate(todo, 1))
                got = dict(c.execute("SELECT doc, term FROM v WHERE doc > 0 AND offset = 0"))
        for i, w in enumerate(todo, 1):
            _STEMS[w] = got.get(i, w)
    return _STEMS


def keys(found: Iterable[str]) -> dict[str, str]:
    """Each lower-cased word as okl matches it: its stem when the index stems, else the word."""
    ws = list(found)
    if not stemmed():
        return {w: w for w in ws}
    m = stems(ws)
    return {w: m[w] for w in ws}


def words(text: str) -> set[str]:
    """Lower-cased runs of Unicode letters and digits, the task's tokenization (core.briefing_terms),
    each as okl matches it (keys)."""
    return set(keys(set(_WORD.findall(text.lower()))).values())


def about_text(n: Node) -> str:
    """What a lesson says it is about and when it applies: title, symptom, aliases, triggers."""
    return " ".join(x or "" for x in (n.title, n.symptom, n.aliases, n.triggers))


class Rarity:
    """Inverse document frequencies over a store's live records' whole text."""

    def __init__(self, nodes: Iterable[Node]) -> None:
        found = [set(_WORD.findall(" ".join(x or "" for x in (about_text(node), node.body, node.fix)).lower()))
                 for node in nodes]
        if stemmed():   # the whole store's words stemmed in one pass, not a record at a time
            m = stems(w for f in found for w in f)
            found = [{m[w] for w in f} for f in found]
        self.df: dict[str, int] = {}
        self.n = len(found)
        for f in found:
            for w in f:
                self.df[w] = self.df.get(w, 0) + 1
        self.top = math.log((self.n + 1) / 1.5)   # the IDF of a word in exactly one record

    def idf(self, word: str) -> float:
        """Smoothed: a word in no record is the rarest; one in every record is near zero."""
        return math.log((self.n + 1) / (self.df.get(word, 0) + 0.5))

    def relative(self, word: str) -> float:
        """The word's IDF over the largest a word in this store has: 1.0 for a word in one record."""
        return self.idf(word) / self.top if self.top > 0 else 0.0


def score(terms: list[str], node: Node, rarity: Rarity) -> tuple[float, list[str]]:
    """The candidate's score and the subject words its about-text holds, as the prompt has them.
    Stemmed, a stem counts once however many of the prompt's words share it, as on the bench
    that set the line (REPORT §4ac)."""
    about = words(about_text(node))
    k = keys(t.lower() for t in terms)
    seen: set[str] = set()
    shared = []
    for t in terms:
        key = k[t.lower()]
        if key in about and key not in seen:
            seen.add(key)
            shared.append(t)
    return len(shared) + sum(rarity.relative(k[t.lower()]) for t in shared) / 1000, shared


def select(candidates: list[Node], task_terms: list[str], rarity: Rarity, *,
           meaning: dict[str, float] | None = None, weight: float = 0.0,
           line: float | None = None) -> tuple[list[Node], dict[str, list[str]], int]:
    """The candidates that clear the line, best first, the subject words each shares, and how
    many fell below the line. The cap is the caller's cutoff (core.check keeps at most
    CALIBRATED_CAP), so what it trims is counted as trimmed, not as below the line.

    With `meaning` (each lesson's best cosine with the prompt, from the warm model), the score
    adds `weight` times it and the line is `line`, set the same way for that score (§4w, §4z)."""
    terms = [t.lower() for t in task_terms]
    cos = meaning or {}
    scored = []
    for rank, node in enumerate(candidates):
        s, shared = score(terms, node, rarity)
        # A lesson the model has no vector for (recorded since the last index) is scored on its
        # words alone, so it answers to the line set for words alone (review on #300).
        bar = line if line is not None and node.id in cos else CALIBRATED_LINE
        scored.append((s + weight * cos.get(node.id, 0.0), rank, node, shared, bar))
    kept = sorted((x for x in scored if x[0] >= x[4]), key=lambda x: (-x[0], x[1]))
    matched = {x[2].id: x[3] for x in scored}
    return [x[2] for x in kept], matched, len(scored) - len(kept)
