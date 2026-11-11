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


def test_the_reports_figures_are_the_receipts():
    """§4aw's result quotes these; each is read from the committed receipt."""
    receipt = json.loads(sorted((REPO / "evals" / "results").glob("outcome-replay-2*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = report[report.index("## 4aw."):report.index("## 5. Findings")]
    flat = " ".join(section.split())
    names = {"N": "N: no lesson", "T": "T: the lesson as stored", "C": "C: contract", "D": "D: contract and example"}
    for arm, name in names.items():
        row = f"| {name} | {receipt['pass_rate'][arm]} | {receipt['edited'][arm]} of {receipt['sessions_per_arm'][arm]} |"
        assert row in section, row
    assert f"C minus T is {receipt['contract_gain']} and C is at or above T on {receipt['contract_at_least_today_on']} of the 5" in flat
    assert f"D minus C is {receipt['example_gain']}" in flat
    assert f"${receipt['api_priced_usd']} API-priced" in flat
    assert receipt["sessions"] == 100 and not receipt["lead"] and not any(receipt["sessions_with_harm"].values())


def _list_module():
    spec3 = importlib.util.spec_from_file_location("replay_list", REPO / "evals" / "replay_list.py")
    assert spec3 and spec3.loader
    mod = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(mod)
    return mod


def test_each_list_holds_nine_others_and_none_gives_the_bug_away():
    """§4ax's lists: nine other lessons, never the right one, none citing the task or its test."""
    lists = json.loads(_list_module().LISTS.read_text())
    for t in replay.tasks():
        others = lists[str(t["pr"])]["others"]
        assert len(others) == 9 and len({o["id"] for o in others}) == 9, t["pr"]
        assert t["lesson"] not in {o["id"] for o in others}, t["pr"]
        for other in others:
            assert f"#{t['pr']}" not in other["text"] and t["grader"] not in other["text"], (t["pr"], other["id"])


def test_each_arm_of_the_list_test_gets_what_it_should():
    """Alone has one lesson, ten has ten including the right one, and only told says it bears."""
    rl = _list_module()
    for t in replay.tasks():
        for rep in range(replay.REPEATS):
            alone, ten = rl.told(t, "alone_plain", rep), rl.told(t, "ten_plain", rep)
            assert alone.count("<lesson>") == 1 and ten.count("<lesson>") == 10
            assert t["lesson_text"].strip() in alone and t["lesson_text"].strip() in ten
            assert "bear" not in alone and "bear" not in ten
            assert "bears on this change" in rl.told(t, "alone_told", rep) and "bear on this change" in rl.told(t, "ten_told", rep)


def test_the_list_reading_follows_the_stated_rule():
    """Held, rescued or collapsed, against the alone-and-told arm, and nothing until complete."""
    rl = _list_module()
    base = {"alone_told": 0.6, "alone_plain": 0.5}
    assert rl.reading({**base, "ten_plain": 0.45, "ten_told": 0.1}, True) == "holds in a list"
    assert rl.reading({**base, "ten_plain": 0.2, "ten_told": 0.5}, True) == "the sentence rescues it"
    assert rl.reading({**base, "ten_plain": 0.2, "ten_told": 0.2}, True) == "collapses in a list"
    assert rl.reading({**base, "ten_plain": 0.6, "ten_told": 0.6}, False) == "not complete"


def test_the_list_results_figures_are_the_receipts():
    """§4ax's result quotes these; each is read from the committed receipt."""
    receipt = json.loads(sorted((REPO / "evals" / "results").glob("replay-list-2*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = report[report.index("## 4ax."):report.index("## 5. Findings")]
    names = {"alone_told": "alone, told", "alone_plain": "alone, plain", "ten_told": "ten, told", "ten_plain": "ten, plain"}
    for arm, name in names.items():
        assert f"| {name} | {receipt['pass_rate'][arm]} | {receipt['edited'][arm]} of 25 |" in section, arm
    assert receipt["reading"] == "collapses in a list" and receipt["sessions"] == 100
    edited = receipt["edited"]
    flat = " ".join(section.split())
    assert f"edited in {edited['ten_told'] + edited['ten_plain']} of 50 sessions, against {edited['alone_told'] + edited['alone_plain']} of 50 alone" in flat
    assert not any(receipt["sessions_with_harm"].values())


def _one_module():
    spec4 = importlib.util.spec_from_file_location("replay_one", REPO / "evals" / "replay_one.py")
    assert spec4 and spec4.loader
    mod = importlib.util.module_from_spec(spec4)
    spec4.loader.exec_module(mod)
    return mod


def test_one_at_a_time_asks_about_the_same_ten_in_the_same_order():
    """§4ay hands over §4ax's list: ten lessons, one of them right, in the list's own place."""
    one, rl = _one_module(), _list_module()
    for t in replay.tasks():
        for rep in range(replay.REPEATS):
            lessons = one.order(t, rep)
            assert len(lessons) == 10 and sum(right for right, _ in lessons) == 1
            assert lessons[rl.position(t["pr"], rep)] == (True, t["lesson_text"].strip())
            listed = rl.told(t, "ten_plain", rep)
            assert [listed.index(text) for _, text in lessons] == sorted(listed.index(text) for _, text in lessons)


def test_the_one_at_a_time_reading_follows_the_stated_rule():
    """No better, short of alone, works, or noisy, against the same sitting's list and lesson alone."""
    one = _one_module()
    arm = one.ONE
    quiet = {arm: 0, "ten_plain": 0, "alone_told": 0}
    base = {"ten_plain": 0.2, "alone_told": 0.6}
    assert one.reading({**base, arm: 0.4}, True, 0, quiet) == "no better than the list"
    assert one.reading({**base, arm: 0.45}, False, 0, quiet) == "not complete"
    assert one.reading({**base, arm: 0.45 - 0.01 + 0.01}, True, 0, quiet) in ("works", "better than the list, short of alone")
    assert one.reading({**base, arm: 0.5}, True, 2, quiet) == "works"
    assert one.reading({**base, arm: 0.5}, True, 3, quiet) == "catches it, but noisy"
    assert one.reading({**base, arm: 0.5}, True, 0, {**quiet, arm: 3}) == "catches it, but noisy"
    low = {"ten_plain": 0.1, "alone_told": 0.8}
    assert one.reading({**low, arm: 0.4}, True, 0, quiet) == "better than the list, short of alone"
