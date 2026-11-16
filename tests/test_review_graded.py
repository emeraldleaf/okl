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


def _section() -> str:
    report = (REPO / "evals" / "REPORT.md").read_text()
    start = report.index("## 4bj.")
    return report[start:report.index("\n## ", start + 1)]


def test_the_section_states_the_reviews_as_the_manifest_records_them():
    """The pre-registration's counts are the manifest's: lessons listed, right lessons written later, those
    governing a changed file, the lesson left out, and the changes the tasks come from."""
    from statistics import median
    text, rows = _section(), json.loads(graded.MANIFEST.read_text())
    broken = {t["id"] for t in graded.tasks() if not t.get("needs_nothing")}
    mine = [r for r in rows["tasks"] if r["id"] in broken]
    listed = [r["lessons_listed"] for r in mine]
    assert f"list {min(listed)} to {max(listed)} lessons (median {median(listed):g})" in text
    assert f"which is so for {sum(r['right_written_later'] for r in mine)} of the 43" in text
    governs = [r["id"] for r in mine if r["right_governs_a_changed_file"]]
    assert f"in {len(governs)} of the 43 tasks\n({', '.join(governs)})" in text
    assert f"this checkout's store ({rows['store']['records']} records)" in text
    dropped = {i for r in rows["tasks"] for i in r["dropped_citing_the_change"]}
    assert dropped == {"remote-timeout-not-a-deadline"} and "`remote-timeout-not-a-deadline`" in text
    changes = len({t["frozen"] for t in graded.tasks() if t["id"] in broken})
    assert f"§4bi's 29, from {changes} distinct changes" in text and f"43 tasks come from {changes} changes" in text


def test_the_section_quotes_its_check_receipt():
    """The grader check it cites exists, read every grader as checked, and ran on committed code."""
    text = _section()
    name = "review-graded-check-20261115-2310.json"
    receipt = json.loads((REPO / "evals" / "results" / name).read_text())
    assert name in text and f"all {receipt['tasks']} read as checked" in text
    assert receipt["read_as_checked"] == receipt["tasks"] == 48 and receipt["wrong"] == []
    assert not str(receipt["okl_commit"]).endswith("+dirty")


RESULT = "review-graded-20261116-0254.json"


def _result() -> dict:
    return json.loads((REPO / "evals" / "results" / RESULT).read_text())


def test_the_result_reads_its_receipt():
    """The table, the contrast and the reading in §4bj's result are the committed receipt's, from clean code
    that did not move during the run."""
    text, r = " ".join(_section().split()), _result()
    assert RESULT in text and r["sessions"] == r["of"] == 192
    assert r["okl_commit"] == r["okl_commit_at_start"] and not str(r["okl_commit"]).endswith("+dirty")
    assert f"at {r['okl_commit']}, whose code the sessions ran" in text
    assert r["reading"] == "helps, under the bar" and "**Result (2026-11-16): it helps, under the bar.**" in text
    for arm in graded.ARMS:
        row = (f"| {arm} | {r['pass_rate'][arm]} | ", f"| {r['edited'][arm]} of {r['done_per_arm'][arm]} | "
               f"${r['usd_per_session'][arm]:.3f} | {round(r['median_seconds'][arm])} s |")
        assert all(part in text for part in row), arm
    c = r["contrast"]["against"]
    assert f"the review passed {c['mean']} more often than no review, with a 95% interval of {c['ci95'][0]} to " \
           f"{c['ci95'][1]}" in text
    assert f"the interval is {c['ci95_by_change'][0]} to {c['ci95_by_change'][1]}" in text
    assert f"({r['review_sessions_that_started_a_sub_agent']:.1%}) started a sub-agent, a median of " \
           f"{r['sub_agents_median']}" in text
    out, ins = r["not_read"]["out_of_sample"], r["not_read"]["in_sample"]
    assert f"a gain of {out['mean']} ({out['ci95'][0]} to {out['ci95'][1]})" in text
    assert f"(gain {ins['mean']}, 95% interval {ins['ci95'][0]} to {ins['ci95'][1]})" in text
    assert "0.432) and 7 of the 49" in text and r["pass_rate_when_handed_and_not"] == {"handed": 0.432,
                                                                                        "not_handed": 0.143}
    assert r["controls_broken"] == {"none": 0, "review": 0} and r["sessions_with_harm"] == {"none": 0, "review": 0}
    assert f"${r['api_priced_usd']} in all" in text
    ratio = r["usd_per_session"]["review"] / r["usd_per_session"]["none"]
    assert f"{ratio:.1f} times one without" in text


def _two(x: float) -> str:
    """A receipt's three-place figure to two places, half up, as a reader rounds it: 0.145 is 0.15
    (the exact out-of-sample gain is 9/62, 0.1452), where float formatting gives 0.14."""
    from decimal import ROUND_HALF_UP, Decimal
    return str(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def test_the_docs_quote_the_measured_gain_as_the_receipt_has_it():
    """The pre-registered follow-up: the docs say the gain was measured, in the receipt's figures, rounded."""
    r = _result()
    c, out = r["contrast"]["against"], r["not_read"]["out_of_sample"]
    gain = f"a gain of {_two(c['mean'])} (95% interval {_two(c['ci95'][0])} to {_two(c['ci95'][1])})"
    passed = f"passed {_two(r['pass_rate']['review'])} of its sessions against {_two(r['pass_rate']['none'])}"
    for doc in ("README.md", "docs/COSTS-AND-KNOBS.md"):
        flat = " ".join((REPO / doc).read_text().split())
        assert gain in flat and passed in flat and RESULT in flat, doc
        assert f"{_two(out['mean'])} on the 31" in flat or f"the gain was {_two(out['mean'])}" in flat, doc
        assert f"${_two(r['usd_per_session']['review'])} API-priced" in flat, doc
