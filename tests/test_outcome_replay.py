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


def test_the_one_at_a_time_figures_are_the_receipts():
    """§4ay's result quotes these; each is read from the committed receipt."""
    receipt = json.loads(sorted((REPO / "evals" / "results").glob("replay-one-2*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = report[report.index("## 4ay."):report.index("## 5. Findings")]
    flat = " ".join(section.split())
    r, e, u, t = receipt["pass_rate"], receipt["edited"], receipt["usd_per_session"], receipt["median_seconds"]
    for arm, name in (("alone_told", "alone"), ("ten_plain", "list"), ("one_at_a_time", "one at a time")):
        assert f"| {name} | {r[arm]} | {e[arm]} of 25 | ${u[arm]} | {round(t[arm])} s |" in section, arm
    assert receipt["reading"] == "works" and receipt["sessions"] == 75
    assert f"made {receipt['other_edits_median']} edit for the nine other lessons ({receipt['other_edits_total']} edits in {receipt['other_passes']} such passes)" in flat
    assert not any(receipt["sessions_with_harm"].values())


def _e2e_module():
    spec5 = importlib.util.spec_from_file_location("review_e2e", REPO / "evals" / "review_e2e.py")
    assert spec5 and spec5.loader
    mod = importlib.util.module_from_spec(spec5)
    spec5.loader.exec_module(mod)
    return mod


def test_the_end_to_end_arms_differ_only_in_the_review_steps():
    """§4az: one pass is the steps before #427, each alone is today's, and they share everything else."""
    e2e = _e2e_module()
    from okl import core
    assert e2e.STEPS["review_each_alone"] == core.REVIEW_STEPS
    assert e2e.STEPS["review_one_pass"] != core.REVIEW_STEPS
    assert e2e.STEPS["review_one_pass"][:2] == core.REVIEW_STEPS[:2]
    assert "sub-agent" not in " ".join(e2e.STEPS["review_one_pass"])


def test_the_stream_counts_sub_agents_and_finds_the_result():
    """A stream-json run: tool_use events naming the sub-agent tool are counted, and the last result kept."""
    e2e = _e2e_module()
    lines = [json.dumps({"type": "system", "message": "started"}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Agent"}, {"type": "text"}]}}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Task"}]}}),
             "not json", json.dumps({"type": "result", "result": "done", "num_turns": 3})]
    result, agents = e2e.stream("\n".join(lines))
    assert agents == 2 and result == {"type": "result", "result": "done", "num_turns": 3}


def test_the_end_to_end_reading_follows_the_stated_rule():
    """Not followed, on by default, or stays opt-in, against the same sitting's arms."""
    e2e = _e2e_module()
    rate = {"none": 0.0, "review_one_pass": 0.2, "review_each_alone": 0.5}
    quiet = {a: 0 for a in e2e.ARMS}
    assert e2e.reading(rate, True, 0.4, quiet) == "the new steps were not followed"
    assert e2e.reading(rate, True, 0.8, quiet) == "on by default"
    assert e2e.reading({**rate, "review_each_alone": 0.3}, True, 0.8, quiet) == "stays opt-in"
    assert e2e.reading(rate, True, 0.8, {**quiet, "review_each_alone": 3}) == "stays opt-in"
    assert e2e.reading(rate, False, 0.8, quiet) == "not complete"


def _plan_module():
    spec6 = importlib.util.spec_from_file_location("plan_reach", REPO / "evals" / "plan_reach.py")
    assert spec6 and spec6.loader
    mod = importlib.util.module_from_spec(spec6)
    spec6.loader.exec_module(mod)
    return mod


def test_the_plan_reading_follows_the_stated_rule():
    """The plan finds it only when it is good on its own and clearly better than the task's words."""
    plan = _plan_module()
    assert plan.reading({"task": 0.2, "plan": 0.6, "diff": 0.5}, True) == "the plan finds it"
    assert plan.reading({"task": 0.4, "plan": 0.6, "diff": 0.5}, True) == "the plan does not find it well enough"
    assert plan.reading({"task": 0.0, "plan": 0.5, "diff": 0.5}, True) == "the plan does not find it well enough"
    assert plan.reading({"task": 0.0, "plan": 1.0, "diff": 1.0}, False) == "not complete"


def test_a_pick_is_read_from_the_last_array_of_ids():
    """A reply may quote a short list in prose before its answer; the answer is the last array."""
    plan = _plan_module()
    assert plan.last_array('I considered ["a"] first.\n["x", "y", "z"]') == ["x", "y", "z"]
    assert plan.last_array("no answer") is None


def test_the_plan_results_figures_are_the_receipts():
    """§4ba's result quotes these; each is read from the committed receipt."""
    receipt = json.loads(sorted((REPO / "evals" / "results").glob("plan-reach-2*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = report[report.index("## 4ba."):report.index("## 5. Findings")]
    hit, per = receipt["hit_rate"], receipt["per_task"]
    for arm in ("task", "plan", "diff"):
        cells = " | ".join(str(per[arm][k]) for k in ("115", "168", "196", "198", "309"))
        assert f"| {arm} | {hit[arm]} | {cells} |" in section, arm
    assert receipt["reading"] == "the plan does not find it well enough" and receipt["picks"] == 75
