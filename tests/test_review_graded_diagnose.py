"""REPORT §4bk: the receipt's summary is what its sessions say, the verdict classes cover exactly the handed
sessions, and the section quotes the receipt.

Reads only committed files: the transcripts the diagnosis read are private and are not in CI
(lesson n_119528a07fa5).
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parent.parent
RECEIPT = "review-graded-diagnosis-20261116-0444.json"


def _load(name: str):
    sys.path.insert(0, str(REPO / "evals"))
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


diagnose = _load("review_graded_diagnose")


def _receipt() -> dict:
    return json.loads((REPO / "evals" / "results" / RECEIPT).read_text())


def _section() -> str:
    report = (REPO / "evals" / "REPORT.md").read_text()
    start = report.index("## 4bk.")
    return " ".join(report[start:report.index("\n## ", start + 1)].split())


def test_the_receipt_is_of_4bj_run_on_clean_code_and_calls_no_model():
    """The diagnosis reads §4bj's receipt's sessions, ran on committed code, and says no model was called rather
    than carrying the clean_env stamp an import sets (#479)."""
    r = _receipt()
    assert r["of_receipt"] == "review-graded-20261116-0321.json"
    assert (REPO / "evals" / "results" / r["of_receipt"]).exists()
    assert not str(r["okl_commit"]).endswith("+dirty") and r["model_env"] == "none: no model is called"
    run = json.loads((REPO / "evals" / "results" / r["of_receipt"]).read_text())
    review = {(x["id"], x["rep"]): x for x in run["rows"] if x["arm"] == "review"}
    for s in r["sessions"]:
        row = review[(s["id"], s["rep"])]
        assert (s["passed"], s["sub_agents"], s["right_handed"]) == (row["passed"], row["sub_agents"],
                                                                     row["right_checked"])
    assert len(r["sessions"]) == 86


def test_the_verdict_classes_cover_exactly_the_sessions_that_handed_the_right_lesson():
    """A class for every handed session and for no other, from the committed file the receipt hashes."""
    import hashlib
    r, path = _receipt(), REPO / "evals" / "review-graded-4bj-verdicts.json"
    verdicts = json.loads(path.read_text())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == r["verdicts_sha256"]
    handed = {f"{s['id']} review{s['rep']}" for s in r["sessions"] if s["right_handed"]}
    assert set(verdicts["sessions"]) == handed
    assert set(verdicts["sessions"].values()) == {"broken", "not_broken"}
    assert "not blind" in verdicts["classifier"] and r["classifier"] == verdicts["classifier"]


def test_the_summary_is_what_the_sessions_say():
    """Every summary figure recomputed from the receipt's per-session records."""
    r = _receipt()
    ss, sm = r["sessions"], r["summary"]
    step = lambda pred: {"sessions": sum(map(pred, ss)), "passed": sum(s["passed"] for s in ss if pred(s))}  # noqa: E731
    assert sm["steps"] == {
        "never_handed": step(lambda s: not s["right_handed"]),
        "never_handed_no_sub_agent": step(lambda s: not s["right_handed"] and s["sub_agents"] == 0),
        "never_handed_with_sub_agents": step(lambda s: not s["right_handed"] and s["sub_agents"] > 0),
        "handed_called_not_broken": step(lambda s: s["verdict"] == "not_broken"),
        "handed_called_broken": step(lambda s: s["verdict"] == "broken")}
    per_task = Counter()
    for s in ss:
        per_task[s["id"]] += s["right_handed"]
    assert sm["tasks_handed_in"] == {str(k): sum(v == k for v in per_task.values()) for k in (2, 1, 0)}
    assert sm["never_handed_tasks"] == sorted(t for t, v in per_task.items() if v == 0)
    assert sm["handed_median_when_never_handed_with_sub_agents"] == median(
        s["handed"] for s in ss if not s["right_handed"] and s["sub_agents"] > 0)
    dismissed = Counter(s["id"] for s in ss if s["verdict"] == "not_broken")
    assert sm["dismissed_in_both_sessions"] == sorted(t for t, v in dismissed.items() if v == 2)


def test_the_section_quotes_the_receipt():
    """§4bk's table and counts are the receipt's."""
    r, text = _receipt(), _section()
    ss, st = r["sessions"], r["summary"]["steps"]
    assert RECEIPT in text
    for label, key in (("the right lesson reached no sub-agent", "never_handed"),
                       ("of those, the session started no sub-agent", "never_handed_no_sub_agent"),
                       ("of those, it started sub-agents and gave none the right lesson", "never_handed_with_sub_agents"),
                       ("a sub-agent got it and said the change does not break it", "handed_called_not_broken"),
                       ("a sub-agent got it and said the change breaks it", "handed_called_broken")):
        assert f"| {label} | {st[key]['sessions']} | {st[key]['passed']} |" in text, key
    failed = len(ss) - sum(s["passed"] for s in ss)
    lost = {k: st[k]["sessions"] - st[k]["passed"] for k in st}
    assert (f"Of the {failed} failed sessions, {lost['never_handed']} never gave the right lesson to a sub-agent. "
            f"{lost['handed_called_not_broken']} gave it and were told the change does not break it. "
            f"{lost['handed_called_broken']} were told it does") in text
    handed_in = r["summary"]["tasks_handed_in"]
    assert (f"On {handed_in['0']} of the 43 tasks the right lesson reached no sub-agent in either session; on "
            f"{handed_in['1']} it did in one, and on {handed_in['2']} in both") in text
    share = r["summary"]["right_position_share_median"]
    assert f"a median of {share['handed']} of the way down when it was handed, and {share['never_handed']}" in text
    assert r["summary"]["opened_right_when_never_handed"]["with_sub_agents"] == 0
    both_failed = [t for t in r["summary"]["dismissed_in_both_sessions"]
                   if not any(s["passed"] for s in ss if s["id"] == t)]
    assert f"both failed: {', '.join(both_failed)}." in text
    alone = [s for s in ss if s["sub_agents"] == 0]
    opened = [s for s in alone if s["opened_right"]]
    assert (f"Of the {len(alone)} sessions that started none, {len(opened)} opened the right lesson's file "
            f"themselves, and {sum(s['passed'] for s in opened)} of those passed") in text


def test_a_room_with_an_underscore_is_found_under_its_hyphened_name(tmp_path, monkeypatch):
    """Claude Code names a transcript folder after the working directory with '_' turned into '-'; matching the
    room name as written found no folder for 13 of the 96 review sessions."""
    projects = tmp_path / ".claude" / "projects"
    (projects / "-private-var-T-okl-4aw-ab-cd").mkdir(parents=True)
    monkeypatch.setattr(diagnose.Path, "home", classmethod(lambda cls: tmp_path))
    assert diagnose._room({"room": "okl-4aw-ab_cd"}).name == "-private-var-T-okl-4aw-ab-cd"
    assert diagnose._room({"room": "okl-4aw-zz_zz"}) is None


def test_a_message_whose_content_is_a_string_is_read_as_text():
    """A sub-agent's first user message is a bare string; reading only list parts missed the prompt that names
    the lesson, so the right lesson's sub-agent went unfound."""
    events = [{"type": "user", "message": {"content": "check review-lessons/x.md"}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "Verdict: no."}]}}]
    assert list(diagnose._parts(events, "user")) == [{"type": "text", "text": "check review-lessons/x.md"}]
    assert [p["text"] for p in diagnose._parts(events, "assistant")] == ["Verdict: no."]
