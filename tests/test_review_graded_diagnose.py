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
RECEIPT = "review-graded-diagnosis-20261116-0506.json"


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


def test_the_reading_files_cover_exactly_what_the_sessions_give():
    """A verdict class for every session that handed the right lesson and no other, the in-part ones among the
    breaks, and a fit reading for exactly the never-handed tasks and those dismissed twice and failed twice: each
    from a committed file the receipt hashes."""
    import hashlib
    r = _receipt()
    vpath, fpath = REPO / "evals" / "review-graded-4bj-verdicts.json", REPO / "evals" / "review-graded-4bj-fit.json"
    verdicts, fit = json.loads(vpath.read_text()), json.loads(fpath.read_text())
    assert hashlib.sha256(vpath.read_bytes()).hexdigest() == r["verdicts_sha256"]
    assert hashlib.sha256(fpath.read_bytes()).hexdigest() == r["fit_sha256"]
    handed = {f"{s['id']} review{s['rep']}" for s in r["sessions"] if s["right_handed"]}
    assert set(verdicts["sessions"]) == handed and set(verdicts["sessions"].values()) == {"broken", "not_broken"}
    assert all(verdicts["sessions"][k] == "broken" for k in verdicts["broken_in_part"])
    assert "not blind" in verdicts["classifier"] and r["classifier"] == verdicts["classifier"]
    assert sorted(fit["never_handed"]) == r["summary"]["never_handed_tasks"]
    assert sorted(fit["dismissed_both_failed"]) == r["summary"]["dismissed_in_both_sessions_both_failed"]


def test_the_summary_is_what_the_sessions_say():
    """Every summary figure recomputed from the receipt's per-session records."""
    r = _receipt()
    ss, sm = r["sessions"], r["summary"]
    step = lambda pred: {"sessions": sum(map(pred, ss)), "passed": sum(s["passed"] for s in ss if pred(s))}  # noqa: E731
    assert sm["sessions"] == len(ss) and sm["passed"] == sum(s["passed"] for s in ss)
    assert sm["steps"] == {
        "never_handed": step(lambda s: not s["right_handed"]),
        "never_handed_no_sub_agent": step(lambda s: not s["right_handed"] and s["sub_agents"] == 0),
        "never_handed_with_sub_agents": step(lambda s: not s["right_handed"] and s["sub_agents"] > 0),
        "never_handed_never_saw_line": step(lambda s: not s["right_handed"] and not s["saw_right_line"]),
        "never_handed_with_sub_agents_saw_line": step(
            lambda s: not s["right_handed"] and s["sub_agents"] > 0 and s["saw_right_line"]),
        "handed_called_not_broken": step(lambda s: s["verdict"] == "not_broken"),
        "handed_called_broken": step(lambda s: s["verdict"] == "broken")}
    per_task = Counter()
    for s in ss:
        per_task[s["id"]] += s["right_handed"]
    assert sm["tasks_handed_in"] == {str(k): sum(v == k for v in per_task.values()) for k in (2, 1, 0)}
    assert sm["never_handed_tasks"] == sorted(t for t, v in per_task.items() if v == 0)
    never_with = [s for s in ss if not s["right_handed"] and s["sub_agents"] > 0]
    assert sm["handed_median_when_never_handed_with_sub_agents"] == median(s["handed"] for s in never_with)
    assert sm["opened_right_when_never_handed"] == {
        "no_sub_agent": sum(s["opened_right"] for s in ss if not s["right_handed"] and s["sub_agents"] == 0),
        "with_sub_agents": sum(s["opened_right"] for s in never_with)}
    share = lambda handed: round(median(s["right_position"] / s["listed"] for s in ss if s["right_handed"] is handed), 2)  # noqa: E731
    assert sm["right_position_share_median"] == {"handed": share(True), "never_handed": share(False)}
    dismissed = Counter(s["id"] for s in ss if s["verdict"] == "not_broken")
    assert sm["dismissed_in_both_sessions"] == sorted(t for t, v in dismissed.items() if v == 2)
    assert sm["list_cut"] == {"sessions": sum(s["list_cut"] for s in ss),
                              "passed": sum(s["list_cut"] and s["passed"] for s in ss)}


def test_the_section_quotes_the_receipt():
    """Every figure in §4bk's prose, from the receipt's sessions, the two reading files and §4bc's receipt."""
    r, text = _receipt(), _section()
    ss, sm, st = r["sessions"], r["summary"], r["summary"]["steps"]
    fit = json.loads((REPO / "evals" / "review-graded-4bj-fit.json").read_text())
    assert RECEIPT in text and f"§4bj's {len(ss)} review sessions on broken tasks" in text
    for label, key in (("the right lesson reached no sub-agent", "never_handed"),
                       ("of those, the session started no sub-agent", "never_handed_no_sub_agent"),
                       ("of those, it started sub-agents and gave none the right lesson", "never_handed_with_sub_agents"),
                       ("a sub-agent got it and said the change does not break it", "handed_called_not_broken"),
                       ("a sub-agent got it and said the change breaks it", "handed_called_broken")):
        assert f"| {label} | {st[key]['sessions']} | {st[key]['passed']} |" in text, key
    failed = len(ss) - sm["passed"]
    lost = {k: st[k]["sessions"] - st[k]["passed"] for k in st}
    assert (f"Of the {failed} failed sessions, {lost['never_handed']} never gave the right lesson to a sub-agent. "
            f"{lost['handed_called_not_broken']} gave it and were told the change does not break it. "
            f"{lost['handed_called_broken']} were told it does, and their fix did not pass the grader; one of those "
            f"{['zero', 'one', 'two', 'three', 'four', 'five', 'six'][lost['handed_called_broken']]} (t45 review1)") in text
    t45 = [s for s in ss if s["id"] == "t45" and s["rep"] == 1][0]
    assert t45["verdict"] == "broken" and not t45["passed"]
    hi = sm["tasks_handed_in"]
    assert (f"On {hi['0']} of the 43 tasks the right lesson reached no sub-agent in either session; on {hi['1']} it "
            f"did in one, and on {hi['2']} in both") in text
    unseen = st["never_handed_never_saw_line"]
    assert unseen["passed"] == 0 and (f"In {unseen['sessions']} of the {st['never_handed']['sessions']} sessions "
                                      f"that never handed it on") in text and f"All {unseen['sessions']} failed" in text
    cut = sm["list_cut"]
    assert (f"a read of the list came back cut in {cut['sessions']}, and {cut['passed']} of those passed, against "
            f"{sm['passed'] - cut['passed']} of the other {len(ss) - cut['sessions']}") in text
    saw = st["never_handed_with_sub_agents_saw_line"]["sessions"]
    n_with = st["never_handed_with_sub_agents"]["sessions"]
    assert f"The other {saw} sessions that started sub-agents had the line in front of them." in text
    assert (f"The {n_with} sessions that started sub-agents without the right lesson handed a median of "
            f"{sm['handed_median_when_never_handed_with_sub_agents']:g} lessons each. None of the {n_with} opened the "
            f"right lesson's file, so in {saw} of them") in text
    assert sm["opened_right_when_never_handed"]["with_sub_agents"] == 0
    share = sm["right_position_share_median"]
    assert f"a median of {share['handed']} of the way down when it was handed, and {share['never_handed']}" in text
    nf = sm["fit"]["never_handed"]
    assert f"each of the {len(fit['never_handed'])} lessons beside its task's defect: {nf['plain']} fit plainly and " \
           f"{nf['moderate']} moderately" in text
    standing = {"n_e7988ff536fb", "n_adea7f2c7373", "n_5ddb0776a863"}
    tasks = {t["id"]: t for t in diagnose.g.tasks()}
    assert standing <= {tasks[t]["lesson"] for t in fit["never_handed"]} and "three lessons" in text
    handed = [s for s in ss if s["right_handed"]]
    called_not = st["handed_called_not_broken"]["sessions"]
    assert f"in {called_not} of {len(handed)} sessions" in text
    both, both_failed = sm["dismissed_in_both_sessions"], sm["dismissed_in_both_sessions_both_failed"]
    words = {6: "six", 8: "Eight"}
    assert f"{words[len(both)]} tasks drew that answer in both sessions. On {words[len(both_failed)]} of them both " \
           f"sessions failed: {', '.join(both_failed)}." in text
    t43, t03 = ([s["passed"] for s in ss if s["id"] == t] for t in ("t43", "t03"))
    assert t43 == [True, True] and sum(t03) == 1 and "On t43 both passed, and on t03 one did." in text
    df = sm["fit"]["dismissed_both_failed"]
    assert df == {"arguable": 1, "loose": 1, "plain": 4} and "On four of the six the lesson fits plainly." in text
    assert fit["dismissed_both_failed"]["t28"][0] == "arguable" and fit["dismissed_both_failed"]["t14"][0] == "loose"
    broke = [s for s in ss if s["verdict"] == "broken"]
    part = [s for s in broke if s["broken_in_part"]]
    whole = [s for s in broke if not s["broken_in_part"]]
    assert f"{sum(s['passed'] for s in broke)} of {len(broke)} sessions passed" in text
    assert all(s["passed"] for s in part) and f"The {['', '', '', '', '', '', 'six'][len(part)]} that named a break " \
        "in part all passed." in text
    assert f"The {['', '', '', '', '', '', '', '', '', '', '', '', 'twelve'][len(whole)]} that named it outright " \
        f"passed {sum(s['passed'] for s in whole)}." in text
    alone = [s for s in ss if s["sub_agents"] == 0]
    opened, closed = [s for s in alone if s["opened_right"]], [s for s in alone if not s["opened_right"]]
    assert (f"Of the {len(alone)} sessions that started none, {len(opened)} opened the right lesson's file "
            f"themselves and {sum(s['passed'] for s in opened)} of those passed. Of the {len(closed)} that did not, "
            f"{sum(s['passed'] for s in closed)} passed, and {sum(not s['saw_right_line'] for s in closed)} of those "
            f"{len(closed)} never saw its line.") in text
    pick = json.loads((REPO / "evals" / "results" / "pick-fix-20261112-0425.json").read_text())
    assert f"held {pick['recall']['pool']} of the broken lessons, against the pick's {pick['recall']['pick']}" in text
    assert round(pick["mean_size"]["pool"]) == 30 and "a pool of about 30 lessons" in text
    changes = len({tasks[t]["frozen"] for t in {s["id"] for s in ss}})
    assert f"43 tasks from {changes} changes" in text


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
