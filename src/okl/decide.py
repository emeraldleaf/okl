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
when what it says it is about holds three of the prompt's subject words, or two that are both
nearly as rare as a word in one record (relative rarities summing past 1.717). It was measured
on one developer's prompts; a store calibrates its own line on its own prompts with the same
procedure (the guarantee is per population).
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Final

from .store import Node

# The bench's conformal line (evals/bench/, REPORT §4w): the 269th of 282 calibration nulls'
# best scores, 2.0017172944, and just above it.
CALIBRATED_LINE = 2.0017173
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


def words(text: str) -> set[str]:
    """Lower-cased runs of Unicode letters and digits, the task's tokenization (core.briefing_terms)."""
    return set(_WORD.findall(text.lower()))


def about_text(n: Node) -> str:
    """What a lesson says it is about and when it applies: title, symptom, aliases, triggers."""
    return " ".join(x or "" for x in (n.title, n.symptom, n.aliases, n.triggers))


class Rarity:
    """Inverse document frequencies over a store's live records' whole text."""

    def __init__(self, nodes: Iterable[Node]) -> None:
        self.df: dict[str, int] = {}
        self.n = 0
        for node in nodes:
            self.n += 1
            for w in words(" ".join(x or "" for x in (about_text(node), node.body, node.fix))):
                self.df[w] = self.df.get(w, 0) + 1
        self.top = math.log((self.n + 1) / 1.5)   # the IDF of a word in exactly one record

    def idf(self, word: str) -> float:
        """Smoothed: a word in no record is the rarest; one in every record is near zero."""
        return math.log((self.n + 1) / (self.df.get(word, 0) + 0.5))

    def relative(self, word: str) -> float:
        """The word's IDF over the largest a word in this store has: 1.0 for a word in one record."""
        return self.idf(word) / self.top if self.top > 0 else 0.0


def score(terms: list[str], node: Node, rarity: Rarity) -> tuple[float, list[str]]:
    """The candidate's score and the subject words its about-text holds."""
    about = words(about_text(node))
    shared = [t for t in terms if t in about]
    return len(shared) + sum(rarity.relative(t) for t in shared) / 1000, shared


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
