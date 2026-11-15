"""REPORT §4bj's instrument: the sessions it plans, how it counts sub-agents, what it hides, and its reading.

Reads only committed files and made-up rows: the sessions and the rendered reviews are private and are not in CI
(lesson n_119528a07fa5).
"""
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load(name: str):
    sys.path.insert(0, str(REPO / "evals"))
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


graded = _load("review_graded")
sandbox = _load("sandbox")


def test_every_task_runs_twice_in_each_arm_in_a_seeded_order():
    """43 broken tasks and five controls, two repeats an arm: 192 sessions, the same order every time."""
    plan = graded.calls()
    assert len(plan) == 192
    assert Counter(c["arm"] for c in plan) == {"none": 96, "review": 96}
    assert set(Counter((c["id"], c["arm"]) for c in plan).values()) == {2}
    assert sum(not t.get("needs_nothing") for t in graded.tasks()) == 43
    assert plan == graded.calls()
    assert [c["arm"] for c in plan[:12]] != ["none"] * 6 + ["review"] * 6


def test_both_arms_run_with_the_sub_agent_tool_and_differ_only_by_the_request():
    """The review needs the Agent tool; giving it to no review too keeps the tools out of the contrast."""
    argv = graded.AGENT
    assert "Agent" in argv[argv.index("--tools") + 1].split(",")
    assert "Agent" in argv and "stream-json" in argv and "--verbose" in argv
    assert "okl check --change" in graded.ASK and "{" not in graded.ASK


def test_a_stream_counts_the_sessions_own_sub_agents_and_not_those_inside_one():
    """Each Agent call the session makes is counted with what it was handed; a call a sub-agent makes is not."""
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "name": "Agent", "input": {"prompt": "lesson n_123: does it break?"}}]}},
        {"type": "assistant", "parent_tool_use_id": "toolu_1", "message": {"content": [
            {"type": "tool_use", "name": "Agent", "input": {"prompt": "nested"}}]}},
        {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_use", "name": "Task", "input": {"prompt": "lesson n_456"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}},
        {"type": "result", "result": "done", "modelUsage": {"claude-sonnet-x": {}}, "num_turns": 4},
    ]
    envelope, agents = sandbox._streamed("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
    assert envelope["result"] == "done"
    assert [a["prompt"] for a in agents] == ["lesson n_123: does it break?", "lesson n_456"]
    assert sandbox._streamed("garbage") == (None, [])
    assert sandbox._json('{"result": "x"}') == {"result": "x"} and sandbox._json("[1]") is None


def test_a_streamed_ask_returns_its_sub_agents_and_a_plain_one_does_not(monkeypatch, tmp_path):
    """sandbox.ask reads stream-json when the argv asks for it, and only then adds the sub-agent fields."""
    lines = [{"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
                {"type": "tool_use", "name": "Agent", "input": {"prompt": "p"}}]}},
             {"type": "result", "result": "ok", "modelUsage": {"claude-sonnet-x": {}}, "num_turns": 2,
              "total_cost_usd": 0.5}]

    class Done:
        returncode, stderr = 0, ""
        stdout = "\n".join(json.dumps(x) for x in lines)

    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(sandbox, "inside_repo", lambda p: False)
    got = sandbox.ask(["claude", "-p", "--output-format", "stream-json", "--verbose"], "hi", model="sonnet",
                      effort="medium", timeout=5, cwd=tmp_path)
    assert got["sub_agents"] == 1 and got["agent_inputs"] == [{"prompt": "p"}] and got["result"] == "ok"
    Done.stdout = json.dumps(lines[-1])
    plain = sandbox.ask(["claude", "-p", "--output-format", "json"], "hi", model="sonnet", effort="medium", timeout=5,
                        cwd=tmp_path)
    assert plain["result"] == "ok" and "sub_agents" not in plain


@pytest.mark.parametrize(("text", "hit"), [("fixed in #30.", True), ("(okl #30)", True), ("#300 and #301", False),
                                           ("see #3", False), ("the grader test_t19_x", True), ("commit 55d649c", True)])
def test_a_lesson_cites_the_change_by_whole_number_grader_or_fixing_commit(text, hit):
    """The lists builder matched '#30' inside '#300'; this does not, so no unrelated lesson is left out."""
    task = {"pr": 30, "grader": "test_t19_x", "end": "55d649ca3b53c3517f35058c12f1848c58a4cb73"}
    assert graded.cites(text, task) is hit


def _store(tmp_path, body):
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("create table node (id text, title text, symptom text, fix text, body text)")
    con.execute("insert into node values ('L', 'a title', 'a symptom', 'do this (here: the fix)', ?)", (body,))
    con.commit()
    return con


def test_a_redaction_removes_its_clause_wherever_the_task_file_says(tmp_path):
    """Named fields, the old 'body: ' form, and unnamed ones found by search all come out."""
    con = _store(tmp_path, "cause: the incident.")
    task = {"id": "t", "lesson": "L", "lesson_redactions": [{"removed": " (here: the fix)"},
                                                            {"removed": "body: cause: the incident."}]}
    graded.redact(con, task)
    assert con.execute("select fix, body from node").fetchone() == ("do this", "")


def test_a_redaction_that_matches_nothing_is_refused(tmp_path):
    """The review would otherwise show a clause the task file says was removed."""
    con = _store(tmp_path, "cause: x")
    with pytest.raises(SystemExit, match="matches nothing"):
        graded.redact(con, {"id": "t", "lesson": "L", "lesson_redactions": [{"field": "body", "removed": "gone"}]})


def _c(mean, lo, hi):
    return {"against": {"mean": mean, "ci95": (lo, hi)}}


@pytest.mark.parametrize(("c", "complete", "followed", "quiet", "said"), [
    (_c(0.3, 0.1, 0.5), False, 1.0, True, "not complete"),
    (_c(0.3, 0.1, 0.5), True, 0.4, True, "the review's steps were not followed"),
    (_c(0.3, 0.1, 0.5), True, 0.9, True, "helps, at the bar"),
    (_c(0.25, 0.01, 0.5), True, 0.9, True, "helps, at the bar"),
    (_c(0.12, 0.02, 0.22), True, 0.9, True, "helps, under the bar"),
    (_c(0.3, 0.1, 0.5), True, 0.9, False, "helps, at the bar, and breaks more"),
    (_c(0.05, -0.05, 0.2), True, 0.9, True, "no gain as large as the bar"),
    (_c(0.1, -0.05, 0.3), True, 0.9, True, "inconclusive"),
    (_c(0.0, 0.0, 0.3), True, 0.9, True, "inconclusive"),
])
def test_the_reading_is_the_one_pre_registered(c, complete, followed, quiet, said):
    """The interval's lower end above 0 reads a gain; its upper end below the bar rules the bar out."""
    assert graded.reading(c, complete, followed, quiet) == said


def test_a_missing_session_counts_against_the_review_in_the_reading():
    """per_task fills a missing review session as a fail and a missing no-review one as a pass."""
    rows = [{"id": "a", "arm": "review", "rep": 0, "passed": True}, {"id": "a", "arm": "none", "rep": 0, "passed": False}]
    assert graded.per_task(rows, "review", ["a"], False) == {"a": 0.5}
    assert graded.per_task(rows, "none", ["a"], True) == {"a": 0.5}
    assert graded.per_task(rows, "review", ["a"], None) == {"a": 1.0}


def test_the_manifest_holds_every_task_with_the_right_lesson_listed():
    """Every task's review was rendered and recorded, and none leaves the right lesson out."""
    rows = {r["id"]: r for r in json.loads(graded.MANIFEST.read_text())["tasks"]}
    assert set(rows) == {t["id"] for t in graded.tasks()}
    assert all(r["right_listed_at"] for r in rows.values())
    assert all(len(r["review_sha256"]) == 64 and len(r["lessons_sha256"]) == 64 for r in rows.values())
