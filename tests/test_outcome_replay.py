"""REPORT §4aw's instrument: what each arm is told, and that nothing in it gives the bug away.

Reads only committed files: the sessions are private and are not in CI (lesson n_119528a07fa5).
"""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("outcome_replay", REPO / "evals" / "outcome_replay.py")
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_every_task_has_a_contract_in_the_agreed_shape():
    """Each lesson under test has a contract with every part, and an example with every part."""
    contracts = json.loads(replay.CONTRACTS.read_text())
    assert {t["lesson"] for t in replay.tasks()} == set(contracts)
    for lesson, c in contracts.items():
        for part in ("WHEN:", "DO:", "DONE WHEN:", "DOES NOT APPLY:", "WHY:"):
            assert part in c["contract"], (lesson, part)
        for part in ("BAD:", "GOOD:", "NOT APPLICABLE:"):
            assert part in c["example"], (lesson, part)


def test_each_arm_is_told_only_what_it_should_be():
    """No lesson, the stored text, the contract alone, and the contract with its example."""
    contracts = json.loads(replay.CONTRACTS.read_text())
    for t in replay.tasks():
        c = contracts[t["lesson"]]
        assert replay.lesson_for(t, "N") == ""
        today, contract, example = (replay.lesson_for(t, a) for a in ("T", "C", "D"))
        assert t["lesson_text"].strip() in today and c["contract"].strip() not in today
        assert c["contract"].strip() in contract and c["example"].strip() not in contract
        assert c["contract"].strip() in example and c["example"].strip() in example


def test_nothing_an_arm_reads_names_the_bug_it_is_graded_on():
    """The lesson, contract and example must not cite the task or its hidden test."""
    for t in replay.tasks():
        for arm in replay.ARMS:
            told = replay.lesson_for(t, arm)
            assert f"#{t['pr']}" not in told and t["grader"] not in told, (t["pr"], arm)
        assert t["grader"] not in replay.task_words(t), t["pr"]


def test_the_order_is_seeded_and_covers_every_session():
    """Stopping early must not favour an arm, and a resume must see the same order."""
    first, second = replay.calls(), replay.calls()
    assert first == second
    assert len(first) == len(replay.tasks()) * len(replay.ARMS) * replay.REPEATS
    assert len({replay.ident(c) for c in first}) == len(first)
    assert [c["arm"] for c in first[:8]] != sorted(c["arm"] for c in first[:8])


def test_the_grader_reads_a_failure_and_a_file_that_did_not_run():
    """A parameter of the grader failing counts; another test failing does not; pytest crashing does."""
    task = {"grader": "test_x"}
    assert replay.grader_failed({"exit": 1, "bad": ["tests/a.py::test_x[p0]"]}, task)
    assert not replay.grader_failed({"exit": 1, "bad": ["tests/a.py::test_other"]}, task)
    assert not replay.grader_failed({"exit": 0, "bad": []}, task)
    assert replay.grader_failed({"exit": 2, "bad": []}, task)


def test_every_task_has_a_grader_that_its_keyword_selects():
    """Each task but #115 (whose own test fails by assertion) is graded by a behaviour test."""
    spec2 = importlib.util.spec_from_file_location("outcome_regrade", REPO / "evals" / "outcome_regrade.py")
    assert spec2 and spec2.loader
    regrade = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(regrade)
    source = regrade.GRADERS.read_text()
    assert set(regrade.KEYWORD) == {t["pr"] for t in replay.tasks()} - {115}
    for key in regrade.KEYWORD.values():
        assert f"def {key}" in source, key
