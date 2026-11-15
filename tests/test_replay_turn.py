"""REPORT §4bg and §4bh's instrument: what each arm is told, the tasks and lists it reads, and the readings.

Reads only committed files and made-up rows: the sessions are private and are not in CI (lesson
n_119528a07fa5).
"""
import importlib.util
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


turn = _load("replay_turn")


def _broken():
    return [t for t in turn.tasks() if not t.get("needs_nothing")]


def test_every_task_has_what_the_harness_and_the_record_need():
    """The fields each session reads, a defect and fix kept for the record, and a grader that exists."""
    graders = turn.GRADERS.read_text()
    ids = [t["id"] for t in turn.tasks()]
    assert len(ids) == len(set(ids))
    for t in turn.tasks():
        for field in ("pr", "title", "issues", "base", "frozen", "end", "lesson", "lesson_text", "grader", "kind",
                      "defect", "fix", "named_file", "fix_files", "lesson_redactions"):
            assert field in t, (t["id"], field)
        assert f"def {t['grader']}(" in graders, t["id"]
        assert t["lesson_text"].startswith(f"[{t['lesson']}]"), t["id"]
        if t.get("needs_nothing"):
            assert t["end"] == t["frozen"] and t["control_mutation"], t["id"]


def test_no_lesson_text_still_holds_what_was_redacted_from_it():
    """A clause naming the task's own fix was removed from the stored text; none came back."""
    for t in turn.tasks():
        for r in t["lesson_redactions"]:
            assert r["removed"] and r["removed"] not in t["lesson_text"], (t["id"], r["removed"])


def test_each_list_holds_nine_others_and_none_gives_the_bug_away():
    """Nine other lessons, never the right one, none citing the task or its grader."""
    lists = json.loads(turn.LISTS.read_text())
    assert set(lists) == {t["id"] for t in turn.tasks()}
    for t in turn.tasks():
        others = lists[t["id"]]["others"]
        assert len(others) == 9 and len({o["id"] for o in others}) == 9, t["id"]
        assert t["lesson"] not in {o["id"] for o in others}, t["id"]
        for other in others:
            assert f"#{t['pr']}" not in other["text"] and t["grader"] not in other["text"], (t["id"], other["id"])


def test_the_ten_lesson_arms_hold_the_right_lesson_once_at_the_same_place():
    """List, in turn and one at a time see the same ten in the same order; only the words around differ."""
    for t in turn.tasks():
        for rep in range(turn.REPEATS):
            order = turn.ten(t, rep)
            assert [right for right, _ in order].count(True) == 1 and order[turn.position(t, rep)][0], t["id"]
            lst, inturn = turn.section(t, "list", rep), turn.section(t, "turn", rep)
            assert lst.count(t["lesson_text"].strip()) == 1 and inturn.count(t["lesson_text"].strip()) == 1
            assert lst.replace(turn.WORDS["list"], "") == inturn.replace(turn.WORDS["turn"], ""), t["id"]


def test_in_turn_asks_in_one_at_a_times_own_words():
    """The check, the fix and the leave-alone clauses are one at a time's, word for word."""
    one = turn.WORDS["one"]
    clause = one[one.index("if the change breaks it"):]
    assert clause in turn.WORDS["turn"]
    assert turn.WORDS["alone"] == "This team keeps the lesson below." and turn.WORDS["list"] == "This team keeps the lessons below."


def test_none_and_alone_are_the_floor_and_the_lesson_by_itself():
    """No lesson at all, and the lesson with no other words than §4ax's alone-plain."""
    for t in turn.tasks():
        assert turn.section(t, "none", 0) == ""
        alone = turn.section(t, "alone", 0)
        assert t["lesson_text"].strip() in alone and "governs" not in alone and "<lessons>" not in alone


def test_the_plan_is_every_arm_of_a_stage_on_every_task_in_a_seeded_order():
    """Stage 1's four arms and stage 2's two on every task, five repeats on a broken one and two on a control;
    each stage shuffled the same way every time, and in turn in both stages as separate sessions."""
    assert turn.STAGES == {1: ("none", "alone", "list", "turn"), 2: ("one", "turn")}
    for stage, arms in turn.STAGES.items():
        planned = turn.calls(stage)
        assert planned == turn.calls(stage) and all(c["stage"] == stage for c in planned)
        for t in turn.tasks():
            reps = turn.CONTROL_REPEATS if t.get("needs_nothing") else turn.REPEATS
            mine = [c for c in planned if c["id"] == t["id"]]
            assert sorted((c["arm"], c["rep"]) for c in mine) == sorted((a, r) for a in arms for r in range(reps))
    assert not {turn.ident(c) for c in turn.calls(1)} & {turn.ident(c) for c in turn.calls(2)}


def _rows(rates: dict[str, dict[str, float]], reps: int = 5) -> list[dict]:
    """Made-up sessions with the given pass rate per arm and task."""
    out = []
    for arm, per in rates.items():
        for tid, rate in per.items():
            passes = round(rate * reps)
            out += [{"stage": 1, "id": tid, "arm": arm, "rep": r, "passed": r < passes} for r in range(reps)]
    return out


def _plan(ids: list[str], arms: tuple[str, ...], reps: int = 5) -> list[dict]:
    return [{"stage": 1, "id": i, "arm": a, "rep": r} for i in ids for a in arms for r in range(reps)]


def test_the_readings_follow_the_stated_rules():
    """A big gain over the list reads as helps; none as not enough; no cost of the list stops the reading.
    Stage 2's pilot: level with one at a time is not worse, far below it is worse."""
    ids = [f"t{i:02d}" for i in range(14)]
    rng = random.Random(1)  # noqa: S311  # NOSONAR - made-up rows, seeded
    base = {i: rng.choice([0.0, 0.2]) for i in ids}
    high = {i: rng.choice([0.8, 1.0]) for i in ids}

    def stage_1(turn_rates, alone_rates):
        plan = _plan(ids, turn.STAGES[1])
        rows = _rows({"none": base, "alone": alone_rates, "list": base, "turn": turn_rates})
        c = {f"{a}-{b}": turn.contrast(rows, plan, a, b, ids) for a, b in turn.PAIRS[1]}
        return turn.read_stage_1(c, complete=True)["reading"]

    def stage_2(turn_rates):
        plan = _plan(ids, turn.STAGES[2])
        rows = _rows({"one": high, "turn": turn_rates})
        return turn.read_stage_2({"turn-one": turn.contrast(rows, plan, "turn", "one", ids)}, complete=True)["reading"]

    assert stage_1(high, high) == "helps"
    assert stage_1(base, high) == "does not help enough to act on"
    assert stage_1(high, base) == "the list did not cost on these tasks"
    assert stage_2(high) == "not worse" and stage_2(base) == "worse"
    assert turn.read_stage_1({}, complete=False) == {"reading": "not complete"}


def test_a_missing_session_counts_against_the_claim_being_read():
    """With every in-turn session missing, the reading's interval counts them as fails, the best case as passes."""
    ids = ["a", "b", "c"]
    plan = _plan(ids, ("turn", "list"))
    rows = _rows({"list": dict.fromkeys(ids, 0.4)})
    c = turn.contrast(rows, plan, "turn", "list", ids)
    assert c["against"]["mean"] == -0.4 and c["for"]["mean"] == 0.6


def test_a_grader_runs_with_briefing_logging_as_the_code_sets_it():
    """One grader's positive control needs logging on; the rest of the clean environment holds."""
    env = turn.grade_env(REPO / "evals")
    assert "OKL_BRIEFING_LOG" not in env and env["OKL_WARM"] == "0"
    assert env["PYTHONPATH"] == str(REPO / "evals" / "src")
    assert not any(k.startswith("GIT_") for k in env)


def test_a_run_will_not_start_on_a_reference_that_does_not_resolve(monkeypatch):
    """A task with no list or a grader that is not in the file stops the run before its first session, and
    so does uncommitted code."""
    t = {**turn.tasks()[0], "id": "tx", "grader": "test_no_such_grader"}
    monkeypatch.setattr(turn, "tasks", lambda: [t])

    class Clean:
        started = ("abc1234", "x")
    monkeypatch.setattr(turn.run_guard, "start", lambda: Clean())
    assert turn.preflight() == ["tx: no list", "tx: no grader test_no_such_grader"]
    Clean.started = ("abc1234+dirty", "x")
    assert turn.preflight()[-1] == "the code this run reads is not committed (abc1234+dirty)"
    Clean.started = ("abc1234", "x")
    monkeypatch.setattr(turn, "REPO", Path(turn.tempfile.gettempdir()) / "okl-run")
    assert "a reboot clears" in turn.preflight()[-1]


def test_stage_two_runs_only_after_stage_one_reads_helps(monkeypatch):
    """One at a time is the costly arm: it runs only when in turn clearly beat the list, as pre-registered."""
    monkeypatch.setattr(turn, "preflight", lambda: [])
    for reading in ("helps, under the bar", "inconclusive", "not complete", "the list did not cost on these tasks"):
        monkeypatch.setattr(turn, "verdict", lambda stage, r=reading: {"reading": r})
        try:
            turn.run(2, limit=0)
        except SystemExit as e:
            assert "stage 2 is not run" in str(e), reading
        else:
            raise AssertionError(f"stage 2 started after {reading!r}")
