"""The graded replay sets beside §4bg's (#457): what each task holds, its lists, and the check that takes a set.

evals/replay_check_4bg.py and evals/replay_lists_4bg.py take a set by name, so one copy of each serves every set
and a combined run over several is possible. Reads only committed files and made-up ones: no grader runs here
(evals/replay_check_4bg.py runs them, and its receipt is the evidence).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SETS = ("4bg", "457")


def _load(name: str):
    sys.path.insert(0, str(REPO / "evals"))
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check = _load("replay_check_4bg")


def _tasks(name: str) -> list[dict]:
    return json.loads(check.set_paths(name)["tasks"].read_text())


@pytest.mark.parametrize("name", SETS)
def test_every_task_has_what_a_replay_and_the_record_need(name):
    """The fields a session reads, a defect and fix kept for the record, a lesson text that is the lesson's, and a
    grader its own set's module defines; a control's end is its frozen commit and it says what breaks it."""
    graders = check.set_paths(name)["graders"].read_text()
    for t in _tasks(name):
        for field in ("pr", "title", "issues", "base", "frozen", "end", "lesson", "lesson_text", "grader", "kind",
                      "defect", "fix", "named_file", "fix_files", "lesson_redactions", "in_sample", "needs_nothing"):
            assert field in t, (name, t["id"], field)
        assert t["set"] == name and t["task_commit"] == t["frozen"], t["id"]
        assert f"def {t['grader']}(" in graders, t["id"]
        assert t["lesson_text"].startswith(f"[{t['lesson']}]"), t["id"]
        assert all(len(t[c]) == 40 for c in ("base", "frozen", "end")), t["id"]
        if t["needs_nothing"]:
            assert t["end"] == t["frozen"] and t["control_mutation"] and not t["fix_files"], t["id"]
        else:
            assert t["end"] != t["frozen"] and t["fix_files"], t["id"]


def test_task_ids_and_graders_are_unique_across_the_sets():
    """A combined run keys rows, patches and receipts by task id, and pytest's -k selects by substring."""
    every = [t for name in SETS for t in _tasks(name)]
    ids = [t["id"] for t in every]
    assert len(ids) == len(set(ids))
    names = [t["grader"] for t in every]
    assert len(names) == len(set(names)), sorted(n for n in set(names) if names.count(n) > 1)
    assert not [a for a in names for b in names if a != b and a in b]
    assert [i for _, i in sorted((int(x[1:]), x) for x in ids)] == [f"t{n:02d}" for n in range(1, len(ids) + 1)]


@pytest.mark.parametrize("name", SETS)
def test_no_lesson_text_still_holds_what_was_redacted_from_it(name):
    """A clause naming the task's own fix, PR or incident was removed from the stored text; none came back."""
    for t in _tasks(name):
        for r in t["lesson_redactions"]:
            assert r["removed"].strip() and r["removed"] not in t["lesson_text"], (t["id"], r["removed"])
            assert r["why"], t["id"]


@pytest.mark.parametrize("name", SETS)
def test_each_list_holds_nine_others_and_none_gives_the_bug_away(name):
    """Nine other lessons, never the right one, none citing the task's PR or its grader."""
    lists = json.loads((REPO / "evals" / f"replay-lists-{name}.json").read_text())
    assert set(lists) == {t["id"] for t in _tasks(name)}
    for t in _tasks(name):
        others = lists[t["id"]]["others"]
        assert len(others) == 9 and len({o["id"] for o in others}) == 9, t["id"]
        assert t["lesson"] not in {o["id"] for o in others}, t["id"]
        for other in others:
            assert f"#{t['pr']}" not in other["text"] and t["grader"] not in other["text"], (t["id"], other["id"])


def test_nothing_a_task_shows_names_its_graders():
    """The alternatives check gives an agent a task's own fields and its frozen tree, and that agent must not have
    seen the graders: no field of a new task names the graders module or the file a replay copies them to."""
    for t in _tasks("457"):
        shown = json.dumps({k: v for k, v in t.items() if k not in ("grader", "test_file", "control_mutation")})
        assert "replay_graders" not in shown and "test_replay_grader" not in shown, t["id"]


def test_a_set_is_found_by_its_name_and_the_default_is_4bg():
    """Each set keeps the same three names; §4bg's are what the script always read, and a bad name is refused."""
    assert check.set_paths("4bg") == {"tasks": check.TASKS, "graders": check.GRADERS,
                                      "alternatives": check.ALTERNATIVES}
    assert check.set_paths("457")["graders"] == REPO / "tests" / "replay_graders_457.py"
    for bad in ("../4bg", "4BG", ""):
        with pytest.raises(ValueError, match="not a set name"):
            check.set_paths(bad)


def test_a_combined_run_reads_every_set_and_refuses_a_shared_id(monkeypatch, tmp_path):
    """Two sets load in order, each task beside its set; an id both hold is refused before any grader runs. A
    receipt over one set names its files as §4bg's receipts did; over several, each set's."""
    (tmp_path / "evals").mkdir()
    (tmp_path / "tests").mkdir()
    for name, ids in (("x1", ["t01", "t02"]), ("x2", ["t03"]), ("x3", ["t02"])):
        (tmp_path / "evals" / f"replay-tasks-{name}.json").write_text(json.dumps([{"id": i} for i in ids]))
        (tmp_path / "tests" / f"replay_graders_{name}.py").write_text(f"# {name}\n")
    monkeypatch.setattr(check, "REPO", tmp_path)

    assert [(s, t["id"]) for s, t in check.load(["x1", "x2"])] == [("x1", "t01"), ("x1", "t02"), ("x2", "t03")]
    with pytest.raises(ValueError, match="t02"):
        check.load(["x1", "x3"])
    one = check.provenance(["x1"])
    assert one["tasks_file"] == "evals/replay-tasks-x1.json" and len(one["sets"]) == 1
    assert {"tasks_sha256", "graders_sha256"} <= set(one)
    both = check.provenance(["x1", "x2"])
    assert "tasks_file" not in both and [s["set"] for s in both["sets"]] == ["x1", "x2"]
    assert check.label(["x1", "x2", "x1"]) == "x1+x2"


RESULTS = REPO / "evals" / "results"
CHECK_FIRST = RESULTS / "replay-check-457-20261115-1800.json"
ALT_FIRST = RESULTS / "replay-alternatives-457-20261115-1904.json"
CHANGED_AFTER_ALTERNATIVES = ["t19", "t26", "t36"]   # strengthened after the first alternatives check
CHANGED_IN_REVIEW = ["t25", "t46"]                   # strengthened from code review on #477, after the second


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(receipt: dict) -> bool:
    """Made from committed code that did not move during the run."""
    return receipt["okl_commit"] == receipt["okl_commit_at_start"] and not receipt["okl_commit"].endswith("+dirty")


def _valid_rows(r: dict) -> None:
    """Every broken task's grader fails on its frozen code by an assertion of its own and passes on the real fix,
    and a control's passes as it stands."""
    controls = {t["id"] for t in _tasks("457") if t["needs_nothing"]}
    assert r["valid"] == r["of"] == len(_tasks("457")) == len(r["rows"]) and r["all_valid"]
    for row in r["rows"]:
        assert row["exit_end"] == 0 and row["ran_end"] > 0, row["id"]
        if row["id"] in controls:
            assert row["exit_frozen"] == 0, row["id"]
        else:
            assert row["exit_frozen"] == 1 and row["own_assertion_frozen"], row["id"]


def test_the_first_receipts_are_the_graders_as_phase_one_left_them():
    """The first validity check passed all 30; the first alternatives check, on the same graders, passed every right
    fix and told 24 of 29 pairs apart. Both were made from committed code before any grader changed, so they read
    a graders file other than today's, which the three strengthened graders account for."""
    first, alt = (json.loads(p.read_text()) for p in (CHECK_FIRST, ALT_FIRST))
    assert first["check"] == "replay-check-457" and "usable" not in first and _clean(first)
    _valid_rows(first)
    assert alt["check"] == "replay-alternatives-457" and "usable" not in alt and _clean(alt)
    assert alt["graders_sha256"] == first["graders_sha256"] != _sha(check.set_paths("457")["graders"])
    assert alt["tasks_sha256"] == first["tasks_sha256"] == _sha(check.set_paths("457")["tasks"])
    assert (alt["valid"], alt["of"]) == (24, 29) and all(r["right_exit"] == 0 for r in alt["rows"])
    assert sorted(r["id"] for r in alt["rows"] if not r["valid"]) == ["t19", "t22", "t26", "t36", "t47"]
    for row in alt["rows"]:
        patches = check.set_paths("457")["alternatives"]
        assert row["right_patch_sha256"] == _sha(patches / f"{row['id']}-right.patch"), row["id"]
        assert row["wrong_patch_sha256"] == _sha(patches / f"{row['id']}-wrong.patch"), row["id"]


def test_every_grader_changed_after_the_alternatives_says_so():
    """A grader strengthened after the alternatives check was not written blind, and says so where it changed."""
    text = check.set_paths("457")["graders"].read_text()
    for tid in CHANGED_AFTER_ALTERNATIVES + CHANGED_IN_REVIEW:
        section = text.split(f"# ---- {tid} · ", 1)[1].split("\n# ---- ", 1)[0]
        assert "after the alternatives check" in section, tid


CHECK_SECOND = RESULTS / "replay-check-457-20261115-1921.json"
ALT_SECOND = RESULTS / "replay-alternatives-457-20261115-1925.json"
SCREEN = RESULTS / "replay-screen-457.json"
POWER = RESULTS / "power-457-20261115-1927.json"
CHECK_FINAL = RESULTS / "replay-check-457-20261115-2012.json"
ALT_FINAL = RESULTS / "replay-alternatives-457-20261115-2015.json"
BY_DESIGN = ["t22", "t47"]   # each wrong fix leaves what the task's real fix itself left
RIGHT_FALLS_SHORT = ["t46"]  # the right fix fails a case the real fix handles (from the review of #477)


def test_the_second_receipts_are_the_graders_after_the_first_changes():
    """After the three changes the alternatives prompted, every grader was valid again, every right fix passed, and
    27 of 29 pairs were told apart. Both receipts read today's tasks and patches, from committed code, and a
    graders file the review of #477 changed again since."""
    second, alt = (json.loads(p.read_text()) for p in (CHECK_SECOND, ALT_SECOND))
    paths = check.set_paths("457")
    first = json.loads(ALT_FIRST.read_text())
    for r in (second, alt):
        assert "usable" not in r and _clean(r) and r["tasks_sha256"] == _sha(paths["tasks"])
        assert r["graders_sha256"] not in (_sha(paths["graders"]), first["graders_sha256"])
    assert second["graders_sha256"] == alt["graders_sha256"]
    _valid_rows(second)
    assert (alt["valid"], alt["of"]) == (27, 29) and all(r["right_exit"] == 0 and r["right_ran"] for r in alt["rows"])
    assert sorted(r["id"] for r in alt["rows"] if not r["valid"]) == BY_DESIGN
    for row in alt["rows"]:
        assert row["right_patch_sha256"] == _sha(paths["alternatives"] / f"{row['id']}-right.patch"), row["id"]
        assert row["wrong_patch_sha256"] == _sha(paths["alternatives"] / f"{row['id']}-wrong.patch"), row["id"]


def test_the_final_receipts_are_the_graders_as_they_are():
    """After the review of #477, every grader is valid again; every right fix passes but t46's, which fails a case
    the real fix handles, and every wrong fix fails but the two that leave what the real fix left. Both receipts
    read today's tasks, graders and patches, from committed code."""
    final, alt = (json.loads(p.read_text()) for p in (CHECK_FINAL, ALT_FINAL))
    paths = check.set_paths("457")
    for r in (final, alt):
        assert "usable" not in r and _clean(r)
        assert r["graders_sha256"] == _sha(paths["graders"]) and r["tasks_sha256"] == _sha(paths["tasks"])
    _valid_rows(final)
    assert sorted(r["id"] for r in alt["rows"] if r["right_exit"] != 0) == RIGHT_FALLS_SHORT
    assert sorted(r["id"] for r in alt["rows"] if r["wrong_exit"] == 0) == BY_DESIGN
    assert sorted(r["id"] for r in alt["rows"] if not r["valid"]) == sorted(BY_DESIGN + RIGHT_FALLS_SHORT)
    assert (alt["valid"], alt["of"]) == (26, 29)
    for row in alt["rows"]:
        if row["right_exit"] != 0:
            assert row["right_exit"] == 1 and "diagnostic-step" in row["right_failing_line"], row["id"]
        assert row["right_patch_sha256"] == _sha(paths["alternatives"] / f"{row['id']}-right.patch"), row["id"]
        assert row["wrong_patch_sha256"] == _sha(paths["alternatives"] / f"{row['id']}-wrong.patch"), row["id"]


def _section() -> str:
    text = (REPO / "evals" / "REPORT.md").read_text()
    return text.split("## 4bi.", 1)[1].split("\n## ", 1)[0]


def test_the_section_names_only_receipts_that_exist():
    """Every receipt the section cites is committed: tracked by git, not only present on this disk."""
    import re
    import subprocess
    sec = _section()
    named = set(re.findall(r"`([\w.-]+-\d{8}-\d{4}\.json|replay-screen-457\.json)`", sec))
    assert {p.name for p in (CHECK_FIRST, ALT_FIRST, CHECK_SECOND, ALT_SECOND, CHECK_FINAL, ALT_FINAL, SCREEN,
                             POWER)} <= named
    tracked = set(subprocess.run(["git", "ls-files", "--", "evals/results"], cwd=REPO, capture_output=True,
                                 text=True, check=True).stdout.split())
    for name in named:
        assert f"evals/results/{name}" in tracked, name


def test_the_section_counts_are_the_screening_records():
    """58 candidates, 26 used, 32 rejected by class, and the defects set aside, as the record holds them; every
    used change is a task's, and every rejected one says why."""
    sec, r = _section(), json.loads(SCREEN.read_text())
    assert (r["candidates"], r["used"], r["rejected"]) == (58, 26, 32) and sum(r["rejected_by_class"].values()) == 32
    assert f"each of\nthe {r['defects_set_aside']} defects" in sec
    assert f"| used: 29 broken tasks and one control | {r['used']} |" in sec
    for row in r["rows"]:
        assert (row["outcome"] == "used") == bool(row["tasks"]), row["pr"]
        assert row["outcome"] == "used" or (row["class"] and row["rejected"]), row["pr"]
    assert {t["pr"] for t in _tasks("457")} == {row["pr"] for row in r["rows"] if row["outcome"] == "used"}
    labels = {"no behaviour": "nothing with behaviour was fixed", "no stored lesson names it": "no stored lesson names",
              "already a §4aw or §4bg task": "already a task of §4aw or §4bg", "never fixed": "never fixed",
              "unreachable without a model or the fix's own names": "reachable only through a model"}
    for cls, n in r["rejected_by_class"].items():
        line = next(ln for ln in sec.splitlines() if ln.startswith("| rejected: ") and labels[cls] in ln)
        assert line.endswith(f"| {n} |"), (cls, line)


def test_the_section_states_the_tasks_as_they_are():
    """The in-sample lessons and the redactions the section counts are the tasks'."""
    sec, broken = _section(), [t for t in _tasks("457") if not t["needs_nothing"]]
    late = [t["id"] for t in broken if t["in_sample"]]
    assert f"The lessons of {len(late)} of the {len(broken)} broken tasks" in sec
    assert ", ".join(late[:-1]) + f" and {late[-1]}" in " ".join(sec.split())
    redacted = [t for t in _tasks("457") if t["lesson_redactions"]]
    clauses = sum(len(t["lesson_redactions"]) for t in redacted)
    assert f"{clauses} clauses from the lessons of\n{len(redacted)} tasks" in sec


def test_the_section_table_is_the_alternatives_receipts():
    """Each task's row: its change and lesson, whether its right fix passed and its wrong fix failed, in the first
    check and in the latest. The three graders the first check prompted are the pairs it alone did not tell apart."""
    sec = _section()
    first = {r["id"]: r for r in json.loads(ALT_FIRST.read_text())["rows"]}
    second = {r["id"]: r for r in json.loads(ALT_SECOND.read_text())["rows"]}
    final = {r["id"]: r for r in json.loads(ALT_FINAL.read_text())["rows"]}
    yes = {True: "yes", False: "no"}

    def wrong_failed(r):
        return r["wrong_exit"] == 1 and r["wrong_own_assertion"]
    for t in _tasks("457"):
        if t["needs_nothing"]:
            continue
        a, b = first[t["id"]], final[t["id"]]
        row = (f"| {t['id']} | #{t['pr']} | `{t['lesson'].split(':')[-1]}` | {yes[a['right_exit'] == 0]} | "
               f"{yes[b['right_exit'] == 0]} | {yes[wrong_failed(a)]} | {yes[wrong_failed(b)]} |")
        assert row in sec, row
    changed = sorted(i for i in first if not first[i]["valid"] and second[i]["valid"])
    assert changed == CHANGED_AFTER_ALTERNATIVES


def test_the_section_power_table_is_its_receipt():
    """Every power figure the section quotes is the receipt's, which was made from committed code."""
    sec, r = _section(), json.loads(POWER.read_text())
    assert "usable" not in r and _clean(r) and r["sims"] == 1000
    review = {(x["tasks"], x["repeats"]): x for x in r["power_review"]}
    cheap = {(x["tasks"], x["repeats"]): x for x in r["power_cheap"]}
    for n, k in ((14, 5), (29, 3), (43, 1), (43, 2), (43, 3), (43, 5)):
        a, b = review[(n, k)], cheap[(n, k)]
        row = (f"| {n} | {k} | {a['beats_none_at_gain']} | {a['beats_none_as_seen']} | {a['beats_none_false_alarm']} |"
               f" {b['not_worse_when_equal']} | {b['not_worse_false_alarm_at_margin']} |")
        assert row in sec, row
    assert r["repeats_needed"]["review_beats_none_at_gain"]["43"] == r["repeats_needed"]["haiku_not_worse_when_equal"]["43"] == 2
    assert r["repeats_needed"]["review_beats_none_at_gain"]["14"] is None
    assert (r["review_gain"], r["cheap_margin"], r["review_true_gain_as_seen"]) == (0.25, 0.15, 0.14)


def test_a_grader_runs_from_its_own_sets_module(monkeypatch, tmp_path):
    """The check copies the graders of the task's own set into the room, not §4bg's."""
    copied = []
    monkeypatch.setattr(check.shutil, "copy", lambda src, dst: copied.append(Path(src)))

    class Ran:
        returncode, stdout, stderr = 0, "1 passed", ""
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: Ran())
    tree = type("T", (), {"path": tmp_path})()
    mine = check.set_paths("457")["graders"]
    assert check.run_grader(tree, "test_t19_pr30", mine)["exit"] == 0
    assert copied == [mine]
