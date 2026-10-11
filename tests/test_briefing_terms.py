"""What a briefing searches on (okl review R7, #178).

Every word of a prompt was OR-ed into the full-text query, so "ok go", "do it" and "what
about this one?" each matched enough of a store to fill the 12-lesson cap: the briefing
was noise on exactly the prompts that carry no subject.
"""
from __future__ import annotations

import pytest

from okl import core
from okl.store import Store

FILLER = ["ok", "k", "yes", "thanks", "ok go", "do it", "yes do it", "go ahead",
          "what about this one?", "ok whats next", "keep going", "sounds good", "lgtm",
          "done?", "why?", "hmm", "try again", "ok now what", "what's next"]


@pytest.mark.parametrize("prompt", FILLER)
def test_a_prompt_with_no_subject_searches_on_nothing(prompt):
    """Replies and go-aheads name no subject, so they search on nothing."""
    assert core.briefing_terms(prompt) == [], prompt


def test_short_subject_words_are_kept_beside_real_ones():
    """A standard stoplist drops two-letter tokens, and that lost the IDOR rule, which
    hangs on `id` (review of R7). They are kept whenever the prompt has a subject."""
    terms = core.briefing_terms("add an id check to the ci job, then port the db layer to go")
    for kept in ("id", "ci", "db", "go", "check", "job", "port", "layer"):
        assert kept in terms, (kept, terms)
    for dropped in ("an", "the", "to", "then"):
        assert dropped not in terms, (dropped, terms)


def test_get_survives_as_the_http_verb():
    """`get` reads like filler, but bait tasks and real ones say GET /orders/{id}."""
    assert "GET" in core.briefing_terms("add GET /orders/{id} that returns the order")


def test_terms_keep_their_order_once_each_and_are_capped():
    """Order kept, duplicates dropped, at most MAX_BRIEFING_TERMS: a pasted log cannot match a whole store."""
    words = [f"word{i}" for i in range(100)]
    task = " ".join(["word0", *words])
    terms = core.briefing_terms(task)
    assert terms == words[:core.MAX_BRIEFING_TERMS]


def _store_with_lessons(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 'okl.db'}")
    for i in range(20):
        core.record(s, id=f"r{i}", type="Rule", scope="org",
                    title=f"do it this way: one rule about what to go and do next {i}",
                    symptom="ok, what about this one", fix="keep going")
    core.record(s, id="ledger", type="Rule", scope="org", title="refunds post to the ledger",
                symptom="a refund endpoint", fix="post after the charge")
    return s


@pytest.mark.parametrize("prompt", ["ok go", "do it", "what about this one?", "", "   "])
def test_check_briefs_nothing_for_a_prompt_with_no_subject(tmp_path, prompt):
    """Even against lessons that are made of those very words. An empty query used to
    fall through to a substring search that matched every record."""
    s = _store_with_lessons(tmp_path)

    result = core.check(s, "r", prompt)

    assert result["match_count"] == 0, result
    s.close()


def test_check_still_briefs_a_real_task(tmp_path):
    """The stoplist quiets filler, not real tasks."""
    s = _store_with_lessons(tmp_path)

    result = core.check(s, "r", "add a refund endpoint that posts to the ledger")

    ids = [a.get("id") for a in result["next_actions"]] + [r["id"] for r in result["rules"]]
    assert "ledger" in ids, result
    s.close()


def test_the_precision_check_passes_on_the_seed_packs():
    """evals/precision.py (R8, #179): on a store of only the committed packs, no filler
    prompt briefs more than its budget. Before the stoplist, 18 of 30 did."""
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "evals" / "precision.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "PRECISION OK" in r.stdout, r.stdout[-1500:] + r.stderr[-500:]
