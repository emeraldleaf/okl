"""REPORT §4bj's instrument: the sessions it plans, how it counts sub-agents, what it hides, and its reading.

Reads only committed files and made-up rows: the sessions and the rendered reviews are private and are not in CI
(lesson n_119528a07fa5).
"""
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from statistics import mean, median

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


@contextmanager
def _store(tmp_path, body):
    """A one-lesson store, closed on exit: on Python 3.13 and later an unclosed connection's
    ResourceWarning surfaced in a later module's tests and failed CI there (#478)."""
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("create table node (id text, title text, symptom text, fix text, body text)")
    con.execute("insert into node values ('L', 'a title', 'a symptom', 'do this (here: the fix)', ?)", (body,))
    con.commit()
    try:
        yield con
    finally:
        con.close()


def test_a_redaction_removes_its_clause_wherever_the_task_file_says(tmp_path):
    """Named fields, the old 'body: ' form, and unnamed ones found by search all come out."""
    task = {"id": "t", "lesson": "L", "lesson_redactions": [{"removed": " (here: the fix)"},
                                                            {"removed": "body: cause: the incident."}]}
    with _store(tmp_path, "cause: the incident.") as con:
        graded.redact(con, task)
        assert con.execute("select fix, body from node").fetchone() == ("do this", "")


def test_a_redaction_that_matches_nothing_is_refused(tmp_path):
    """The review would otherwise show a clause the task file says was removed."""
    with _store(tmp_path, "cause: x") as con, pytest.raises(SystemExit, match="matches nothing"):
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



RESULT = "review-graded-20261116-0321.json"
RUN_COMMIT = "6cb22b8"


def _result() -> dict:
    return json.loads((REPO / "evals" / "results" / RESULT).read_text())


def _from_rows(r: dict) -> dict:
    """Every figure §4bj's result quotes, recomputed from the receipt's rows rather than read from its summary."""
    rows, ts = r["rows"], graded.tasks()
    broken = [t["id"] for t in ts if not t.get("needs_nothing")]
    ins = [t["id"] for t in ts if t["id"] in broken and t.get("in_sample")]
    of = lambda arm, ids: [x for x in rows if x["arm"] == arm and x["id"] in ids]  # noqa: E731
    per = {a: graded.per_task(rows, a, broken, None) for a in graded.ARMS}
    gain = {i: per["review"][i] - per["none"][i] for i in broken}
    handed = [x for x in of("review", broken) if x["right_checked"]]
    not_handed = [x for x in of("review", broken) if not x["right_checked"]]
    alone = [x for x in of("review", broken) if x["sub_agents"] == 0]
    reviews = [x for x in rows if x["arm"] == "review"]
    usd = {a: mean(x["usd"] for x in rows if x["arm"] == a) for a in graded.ARMS}
    secs = {a: median(x["seconds"] for x in rows if x["arm"] == a) for a in graded.ARMS}
    return {
        "per_task": per, "contrast": json.loads(json.dumps(graded.contrast(rows, broken))),
        "split": json.loads(json.dumps({"in_sample": graded.contrast(rows, ins)["as_run"],
                                        "out_of_sample": graded.contrast(rows, [i for i in broken if i not in ins])[
                                            "as_run"]})),
        "out_rates": {a: round(mean(per[a][i] for i in broken if i not in ins), 3) for a in graded.ARMS},
        "pass_rate": {a: round(mean(per[a].values()), 3) for a in graded.ARMS},
        "passes": {a: sum(x["passed"] for x in of(a, broken)) for a in graded.ARMS},
        "sessions": {a: len(of(a, broken)) for a in graded.ARMS},
        "tasks_passed": {a: len({x["id"] for x in of(a, broken) if x["passed"]}) for a in graded.ARMS},
        "edited": {a: sum(x["edited"] for x in of(a, broken)) for a in graded.ARMS},
        "gained": sum(v > 0 for v in gain.values()), "gained_both": sum(v == 1 for v in gain.values()),
        "lost": sum(v < 0 for v in gain.values()),
        "handed": (len(handed), sum(x["passed"] for x in handed)),
        "not_handed": (len(not_handed), sum(x["passed"] for x in not_handed)),
        "alone": (len(alone), sum(x["passed"] for x in alone), sorted({x["id"] for x in alone if x["passed"]})),
        "started": (sum(x["sub_agents"] > 0 for x in reviews), len(reviews)),
        "sub_agents_median": median(x["sub_agents"] for x in reviews),
        "longest": max(x["seconds"] for x in rows),
        "broke": sum(not x["passed"] for x in rows if x["id"] not in broken) + sum(bool(x["harm"]) for x in rows),
        "usd": usd, "cost_ratio": usd["review"] / usd["none"], "time_ratio": secs["review"] / secs["none"],
        "models": {m for x in rows for m in x["models"] or []},
        "commits": {x["okl_commit"][:7] for x in rows},
    }


def test_the_receipts_summary_is_what_its_rows_say():
    """The summary fields the result quotes agree with a recomputation from the 192 rows."""
    r = _result()
    got = _from_rows(r)
    assert r["sessions"] == r["of"] == len(r["rows"]) == 192
    assert got["per_task"] == r["per_task"] and got["contrast"] == r["contrast"]
    assert got["pass_rate"] == r["pass_rate"]
    assert got["split"] == {k: r["not_read"][k] for k in ("in_sample", "out_of_sample")}
    assert got["edited"] == r["edited"] and got["broke"] == 0 and r["reading"] == "helps, under the bar"
    assert got["handed"][0] / got["sessions"]["review"] == pytest.approx(r["right_lesson_handed_to_a_sub_agent"],
                                                                         abs=5e-4)
    assert got["started"][0] / got["started"][1] == pytest.approx(r["review_sessions_that_started_a_sub_agent"],
                                                                  abs=5e-4)
    assert got["sub_agents_median"] == r["sub_agents_median"]


def test_the_sessions_ran_one_commit_on_sonnet_and_were_scored_from_clean_code():
    """Each session's row records the commit it ran: one commit, the one the section names. The guard's
    stamps cover only the scoring, which ran later on committed code."""
    r, text = _result(), " ".join(_section().split())
    got = _from_rows(r)
    assert got["commits"] == {RUN_COMMIT} and [c[:7] for c in r["run_commits"]] == [RUN_COMMIT]
    assert f"a worktree of its own at {RUN_COMMIT}: each session's row in the receipt records that commit" in text
    assert not str(r["okl_commit"]).endswith("+dirty") and r["okl_commit"] == r["okl_commit_at_start"]
    assert got["models"] == {"claude-sonnet-5-5"} and "Every session ran on Sonnet" in text


def test_the_result_states_the_rows_figures():
    """Every count and rate in §4bj's result, as the rows give it."""
    r, text = _result(), " ".join(_section().split())
    got = _from_rows(r)
    assert RESULT in text
    for arm in graded.ARMS:
        row = (f"| {arm} | {got['pass_rate'][arm]} | {got['passes'][arm]} of {got['sessions'][arm]} | "
               f"{got['tasks_passed'][arm]} | {got['edited'][arm]} of {got['sessions'][arm]} | "
               f"${got['usd'][arm]:.3f} | ")
        assert row in text, arm
    c = got["contrast"]["against"]
    assert (f"the review passed {c['mean']} more often than no review, with a 95% interval of {c['ci95'][0]} to "
            f"{c['ci95'][1]}") in text
    assert f"the interval is {c['ci95_by_change'][0]} to {c['ci95_by_change'][1]}" in text
    started, total = got["started"]
    assert (f"{started} of the {total} review sessions ({started / total:.1%}) started a sub-agent, a median of "
            f"{got['sub_agents_median']}") in text
    assert f"The review gained on {got['gained']} tasks, {got['gained_both']} of them in both sessions" in text
    assert got["lost"] == 0 and "and lost on none" in text
    ins, out = got["split"]["in_sample"], got["split"]["out_of_sample"]
    assert f"(gain {ins['mean']}, 95% interval {ins['ci95'][0]} to {ins['ci95'][1]})" in text
    assert (f"it passed {got['out_rates']['review']} against {got['out_rates']['none']}, a gain of {out['mean']} "
            f"({out['ci95'][0]} to {out['ci95'][1]})") in text
    (n_h, p_h), (n_n, p_n) = got["handed"], got["not_handed"]
    assert (f"handed the right lesson to a sub-agent in {n_h} of {got['sessions']['review']} "
            f"({n_h / got['sessions']['review']:.2f})") in text
    assert f"It passed {p_h} of those {n_h} ({p_h / n_h:.3f}) and {p_n} of the {n_n}" in text
    assert f"({p_n / n_n:.3f})" in text and f"{n_h - p_h} of the {n_h} that handed it over still failed" in text
    n_a, p_a, ids = got["alone"]
    assert f"{n_a} review sessions started none, and {p_a} of those passed (on {', '.join(ids[:-1])} and {ids[-1]})" \
        in text
    assert f"the longest took {round(got['longest'])} seconds" in text
    assert f"cost {got['cost_ratio']:.1f} times one without" in text
    assert f"(${got['usd']['review']:.4f} against ${got['usd']['none']:.4f} a session, from the rows)" in text
    assert f"took {got['time_ratio']:.1f} times as long" in text and f"${r['api_priced_usd']} in all" in text


DOCS_QUOTING = ("README.md", "docs/COSTS-AND-KNOBS.md", "docs/GETTING-STARTED.md", "docs/EVALUATION.md",
                "docs/decisions/2026-11-15-review-after-writing-on-by-default.md",
                "docs/decisions/2026-11-15-making-the-review-earn-its-default.md", "src/okl/client.py",
                "src/okl/core.py")


def test_the_docs_quote_the_measured_gain_as_the_rows_give_it():
    """The pre-registered follow-up: every doc that quotes §4bj quotes the rows' gain, the bar inside its interval,
    and, where it gives them, the rows' pass rates, the out-of-sample gain and the cost."""
    got = _from_rows(_result())
    c, out = got["contrast"]["against"], got["split"]["out_of_sample"]
    # The figures rounded so that they misread (0.27 - 0.02 = 0.25, the bar) or rounded twice ($0.86, 8.6
    # times, from the summary's 0.855 and 0.099): the first draft's, which the review of #478 caught.
    stale = ("a gain of 0.24,", "a gain of 0.24 ", "gained 0.24 ", "passed 0.27 ", "0.15 on the 31", "$0.86",
             "8.6 times", "the gain was 0.15")
    for doc in DOCS_QUOTING:
        flat = " ".join((REPO / doc).read_text().split())
        assert f"{c['mean']} over no review" in flat or f"a gain of {c['mean']}" in flat \
            or f"gained {c['mean']} over none" in flat, doc
        assert not [w for w in stale if w in flat], doc
    for doc in ("README.md", "docs/COSTS-AND-KNOBS.md"):
        flat = " ".join((REPO / doc).read_text().split())
        assert (f"passed {got['pass_rate']['review']} of its sessions against {got['pass_rate']['none']}" in flat
                and f"a gain of {c['mean']} (95% interval {c['ci95'][0]:.2f} to {c['ci95'][1]:.2f})" in flat
                and "with an interval that includes it" in flat and RESULT in flat), doc
        assert f"{out['mean']} on the 31" in flat or f"the gain was {out['mean']}" in flat, doc
        assert f"${got['usd']['review']:.2f} API-priced" in flat and f"${got['usd']['none']:.2f}" in flat, doc
        assert f"about {got['cost_ratio']:.1f} times the cost" in flat or doc.endswith("KNOBS.md"), doc
    for doc in ("docs/GETTING-STARTED.md", "docs/decisions/2026-11-15-review-after-writing-on-by-default.md"):
        flat = " ".join((REPO / doc).read_text().split())
        assert f"about {got['cost_ratio']:.1f} times" in flat and f"{out['mean']}" in flat, doc
