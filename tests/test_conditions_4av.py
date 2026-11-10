"""REPORT §4av's instrument: the conditions it tests, and the freeze that guards its test half.

Reads only committed files: the private verdicts and keys are not in CI (lesson n_119528a07fa5).
"""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("conditions_agree", REPO / "evals" / "conditions_agree.py")
assert spec and spec.loader
ca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ca)


def test_every_lesson_tested_has_conditions_and_nothing_else_does():
    """The conditions cover exactly the 20 most-broken lessons, each with two to four questions."""
    conditions = json.loads(ca.CONDITIONS.read_text())
    assert set(conditions) == set(ca.lessons())
    for lesson, c in conditions.items():
        assert c["in_scope"].strip() and c["not_in_scope"].strip(), lesson
        assert 2 <= len(c["questions"]) <= 4, lesson
        assert all("?" in q for q in c["questions"]), lesson


def test_the_test_half_refuses_to_run_until_the_conditions_are_frozen(monkeypatch, capsys):
    """No test-half call is made under conditions the pre-registration has not frozen."""
    monkeypatch.setattr(ca, "FROZEN_CONDITIONS", "0" * 16)
    monkeypatch.setattr(ca, "judge_one", lambda *_: (_ for _ in ()).throw(AssertionError("a call was made")))
    assert ca.run("test", ("A", "B")) == 2
    assert "not frozen" in capsys.readouterr().err


def test_kappa_reads_agreement_beyond_chance():
    """Identical calls are 1, opposite calls are below 0, and one judge calling everything alike is not 1."""
    a = [True, False, True, False]
    assert ca.kappa(a, a) == 1.0
    assert ca.kappa(a, [not x for x in a]) < 0
    assert ca.kappa([True, True, True, False], [True, True, True, True]) == 0.0


def test_a_verdict_missing_its_closing_brace_is_still_read():
    """Fable's habit in the pilot: the object ends at the reason's closing quote."""
    got = ca.verdict_in('Looked at it.\n{"verdict": "broken", "evidence": ["a.py:3"], "reason": "no test asserts it."')
    assert got == {"verdict": "broken", "evidence": ["a.py:3"], "reason": "no test asserts it."}
    assert ca.verdict_in("no object here") is None
