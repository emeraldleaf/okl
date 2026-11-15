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
