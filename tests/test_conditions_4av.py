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


def test_the_reports_figures_are_the_receipts():
    """§4av's result quotes these; each is read from the committed receipt."""
    receipt = json.loads(sorted((REPO / "evals" / "results").glob("conditions-agree-test-*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = " ".join(report[report.index("## 4av."):report.index("## 4aw.") if "## 4aw." in report else report.index("## 5. Findings")].split())
    agree, by_key = receipt["agree_broken_or_not"], receipt["by_key"]
    broken_calls = receipt["broken_calls"]
    assert f"agreed on {agree['A']} of {receipt['complete']} and {agree['B']} of {receipt['complete']}" in section
    assert f"kappa {receipt['kappa']['A']} without the conditions and {receipt['kappa']['B']} with them" in section
    assert f"from {broken_calls['A/sonnet'] + broken_calls['A/fable']} broken calls to {broken_calls['B/sonnet'] + broken_calls['B/fable']}" in section
    assert f"rose from {by_key['broken']['A/both']} to {by_key['broken']['B/both']}" in section
    followed = by_key["followed"]
    assert f"rose from {followed['A/sonnet'] + followed['A/fable']} to {followed['B/sonnet'] + followed['B/fable']}" in section
    assert f"Sonnet called {by_key['broken']['A/sonnet']} of the {by_key['broken']['cases']} broken" in section
