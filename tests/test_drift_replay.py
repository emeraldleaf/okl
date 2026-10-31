"""evals/drift_replay.py (REPORT §4ae): what counts as an event, a pair and a verdict, on a small
history built here, so the replay's numbers rest on tested rules."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
CHECK = "grep -q ok a.txt && echo FINE"


@pytest.fixture
def dr(monkeypatch):
    """evals/drift_replay.py as a module (it is a script, not part of the package), registered
    first: its dataclasses resolve their annotations through sys.modules."""
    spec = importlib.util.spec_from_file_location("drift_replay", HERE / "evals" / "drift_replay.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "drift_replay", mod)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                          capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, files: dict[str, str], stamp: str | None = None, cmd: str = CHECK) -> str:
    """Write `files`, and a snapshot stamping lesson L at commit `stamp` when given; commit."""
    for name, text in files.items():
        (repo / name).write_text(text)
    if stamp:
        rule = {"id": "L", "type": "Rule", "title": "t", "scope": "repo:r", "files": "a.txt",
                "verified_at": 1, "verified_commit": stamp,
                "verified_by": f"`{cmd}` exit 0, matched 'FINE' on commit {stamp[:12]}"}
        (repo / "okl-drift.json").write_text(json.dumps({"format": "okl-drift-snapshot/1", "repo": "r",
                                                          "rules": [rule]}))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    """c0 ok; c1 stamps c0; c2 breaks a.txt; c3 mends it; c4 stamps c3 (an event the check
    needed); c5 changes b.txt only; c6 changes a.txt harmlessly; c7 stamps c6 (an unneeded
    event); c8 re-stamps with a.txt unchanged; c9 changes a.txt; c10 changes it again and stamps
    c9 in the same commit (verified before its code commit)."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    c = {0: _commit(repo, {"a.txt": "ok\n", "b.txt": "x\n"})}
    c[1] = _commit(repo, {}, stamp=c[0])
    c[2] = _commit(repo, {"a.txt": "bad\n"})
    c[3] = _commit(repo, {"a.txt": "ok again\n"})
    c[4] = _commit(repo, {}, stamp=c[3])
    c[5] = _commit(repo, {"b.txt": "y\n"})
    c[6] = _commit(repo, {"a.txt": "ok ok\n"})
    c[7] = _commit(repo, {}, stamp=c[6])
    c[8] = _commit(repo, {}, stamp=c[7])
    c[9] = _commit(repo, {"a.txt": "ok 3\n"})
    c[10] = _commit(repo, {"a.txt": "ok 4\n"}, stamp=c[9])
    return repo, c


def test_a_stamp_is_read_in_either_recorded_form(dr):
    """Older stamps end with the date, newer ones with the commit; both carry the check."""
    assert dr.parse_check("`x y` exit 0, matched 'OK' on commit abc") == ("x y", "OK")
    assert dr.parse_check("`x` exit 0, matched 'OK' @ 2026-09-26T14:07Z") == ("x", "OK")
    assert dr.parse_check("stamped by hand") is None


def test_a_check_that_asks_the_present_is_not_replayed(dr):
    """Live GitHub settings, or the lesson store through the preflight, answer for today."""
    assert dr.outside_commit("gh api repos/o/r --jq x") == "reads live GitHub settings"
    assert "store" in dr.outside_commit("python3 evals/preflight.py && pytest -q")
    assert dr.outside_commit("grep -q ok a.txt") == ""


def test_events_are_classified_as_the_gate_read_them(dr, history):
    """Each replaced stamp against its first parent's, which is what CI's gate compared."""
    repo, c = history
    evs = {(e.p, e.v): e for e in dr.events(dr.snapshot("HEAD", repo), "HEAD", repo)}
    red = evs[(c[0], c[3])]
    assert red.kind == "drift-red" and red.touched == [c[2], c[3]] and red.cmd == CHECK
    assert evs[(c[3], c[6])].kind == "drift-red" and evs[(c[3], c[6])].touched == [c[6]]
    assert evs[(c[6], c[7])].kind == "re-verified, governed content unchanged"
    assert evs[(c[7], c[9])].kind == "verified before its code commit"
    assert evs[("", c[0])].kind == "first stamp"


def test_a_replayed_event_is_needed_only_when_the_check_failed_at_a_change(dr, history, tmp_path):
    """c2 broke the lesson and c3 mended it before the re-verification, which history keeps
    only as a pass at c3; the replay finds the failure at c2."""
    repo, c = history
    evs = {(e.p, e.v): e for e in dr.events(dr.snapshot("HEAD", repo), "HEAD", repo)}
    r = dr.Replayer(tmp_path / "scratch", repo)
    try:
        needed, unneeded = evs[(c[0], c[3])], evs[(c[3], c[6])]
        dr.replay_event(r, needed)
        dr.replay_event(r, unneeded)
        assert (needed.outcome, needed.first_fail) == ("needed", c[2])
        assert unneeded.outcome == "unneeded"
        # A check that does not pass where history says it passed proves nothing here.
        odd = dr.Event("L", c[0], c[3], c[4], "drift-red", "grep -q nope a.txt && echo FINE", "FINE", [c[2]])
        dr.replay_event(r, odd)
        assert odd.outcome == "not reproducible"
    finally:
        r.close()
    assert len(_git(repo, "worktree", "list").splitlines()) == 1    # the scratch worktree is gone


def test_a_merge_that_brings_a_governed_change_is_replayed(dr, tmp_path):
    """The first §4ae run listed an event's commits with `git rev-list -- <files>`, which drops a
    merge whose governed files match one parent. Here main changes a.txt harmlessly, the branch
    breaks u.txt (which the check reads but the lesson does not govern), and only the merge
    holds both; the branch then mends u.txt and re-verifies."""
    cmd = "grep -q ok a.txt && ! grep -q bad u.txt && echo FINE"
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    c0 = _commit(repo, {"a.txt": "ok\n", "u.txt": "fine\n"})
    _commit(repo, {}, stamp=c0, cmd=cmd)
    _git(repo, "checkout", "-q", "-b", "br")
    _commit(repo, {"u.txt": "bad\n"})
    _git(repo, "checkout", "-q", "main")
    main_change = _commit(repo, {"a.txt": "ok 2\n"})
    _git(repo, "checkout", "-q", "br")
    _git(repo, "merge", "-q", "--no-edit", "main")
    merge = _git(repo, "rev-parse", "HEAD")
    mended = _commit(repo, {"u.txt": "fine\n"})
    _commit(repo, {}, stamp=mended, cmd=cmd)
    simplified = _git(repo, "rev-list", "--reverse", f"{c0}..{mended}", "--", "a.txt").split()
    assert merge not in simplified                       # what the first run would have tried
    e = next(e for e in dr.events(dr.snapshot("HEAD", repo), "HEAD", repo) if e.v == mended)
    assert e.kind == "drift-red" and e.touched == [main_change, merge]
    r = dr.Replayer(tmp_path / "scratch", repo)
    try:
        dr.replay_event(r, e)
    finally:
        r.close()
    assert (e.outcome, e.first_fail) == ("needed", merge)


def test_pairs_are_red_where_the_governed_files_left_their_stamp(dr, history, tmp_path):
    """Red or green by the commit's own snapshot, then broken or intact by the check."""
    repo, c = history
    got, left = dr.pairs(dr.snapshot("HEAD", repo), "HEAD", repo)
    by_x = {q.x: q for q in got}
    assert by_x[c[2]].red and by_x[c[2]].stamp == c[0]       # a.txt broken since the c0 stamp
    assert not by_x[c[5]].red and by_x[c[5]].stamp == c[3]   # only b.txt moved
    assert c[0] not in by_x                                    # no snapshot yet
    r = dr.Replayer(tmp_path / "scratch", repo)
    try:
        dr.replay_pair(r, by_x[c[2]])
        dr.replay_pair(r, by_x[c[5]])
    finally:
        r.close()
    assert by_x[c[2]].outcome == "broken" and by_x[c[5]].outcome == "intact"


def test_a_check_runs_without_the_callers_store_or_repository(dr, history, tmp_path, monkeypatch):
    """No OKL_ variable and no git-location variable reaches a check."""
    repo, c = history
    monkeypatch.setenv("OKL_DATABASE_URL", "sqlite:////nowhere/okl.db")
    r = dr.Replayer(tmp_path / "scratch", repo)
    try:
        assert not [k for k in r.env if k.startswith("OKL_") and k != "OKL_WARM_SOCKET"]
        assert "GIT_DIR" not in r.env and r.env["PYTHONPATH"].endswith("/src")
    finally:
        r.close()


def test_the_sample_is_redrawn_the_same_and_the_rates_add_up(dr):
    """The draw depends on the items, not their order; the rates follow from the counts."""
    items = [f"i{n}" for n in range(50)]
    assert dr.draw(items, 5, str) == dr.draw(list(reversed(items)), 5, str)
    assert len(dr.draw(items, 80, str)) == 50
    assert dr.wilson(0, 0) == [0.0, 1.0]
    lo, hi = dr.wilson(5, 100)
    assert (lo, hi) == (0.0215, 0.1118)
    evs = [dr.Event("L", "p", "v", "c", "drift-red", outcome=o) for o in ("needed", "unneeded", "unneeded",
                                                                          "not reproducible")]
    # The same verification seen twice (on its branch and at the merge) counts once.
    evs[1].v = evs[2].v = "v2"
    red = [dr.Pair("L", "x", "s", True, "", "", "broken"), dr.Pair("L", "y", "s", True, "", "", "intact")]
    green = [dr.Pair("L", "z", "s", False, "", "", "intact")] * 3 + [dr.Pair("L", "w", "s", False, "", "", "broken")]
    s = dr.summary(evs, red, green, n_red=100, n_green=400)
    assert s["event_precision"]["rate"] == round(1 / 3, 4) and s["not_reproducible"]["events"] == 1
    assert (s["verification_precision"]["needed"], s["verification_precision"]["decided"]) == (1, 2)
    # 100 red pairs half broken, 400 green pairs a quarter broken: 50 of 150 breaks flagged.
    assert s["red_break_rate"]["rate"] == 0.5 and s["green_miss_rate"]["rate"] == 0.25
    assert s["recall_estimate"] == round(50 / 150, 4)


def test_a_lesson_is_classed_by_what_could_rerun_its_check(monkeypatch):
    """evals/lesson_census.py (REPORT §4ag): drift watches a lesson with files and a check, CI a
    check alone, and nothing a lesson with neither; a hand stamp is not a check."""
    from okl.store import Node
    monkeypatch.setattr(sys, "path", list(sys.path))     # the script puts evals/ on the path
    spec = importlib.util.spec_from_file_location("lesson_census", HERE / "evals" / "lesson_census.py")
    lc = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "lesson_census", lc)
    spec.loader.exec_module(lc)
    stamp = "`pytest -q -k x` exit 0, matched 'passed' on commit abc"

    def node(**kw):
        return Node(type="Rule", title="t", scope="org", **kw)
    assert lc.classify(node(files="a.py", verified_by=stamp)) == "watched"
    assert lc.classify(node(files="a.py")) == "unverified"
    assert lc.classify(node(verified_by=stamp)) == "checked"
    assert lc.classify(node(verified_by="stamped by hand")) == "unchecked"


def test_the_stale_lesson_judge_reads_only_a_valid_verdict_and_counts_by_role(monkeypatch):
    """§4ag: a planted fact replaces whole tokens only; an answer without a valid verdict is no
    verdict; the stale rate is stale / (current + stale) among the population alone."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("lesson_census", HERE / "evals" / "lesson_census.py")
    lc = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "lesson_census", lc)
    spec.loader.exec_module(lc)
    assert lc.plant("edit store.py, not okl-store.py or store.pyc", "store.py", "storage.py") \
        == "edit storage.py, not okl-store.py or store.pyc"
    assert lc.plant("pass --repo, not --repo-name", "--repo", "--name") == "pass --name, not --repo-name"
    assert lc.parse_verdict('Here: {"verdict": "stale", "checkable": true}')["verdict"] == "stale"
    assert lc.parse_verdict('{"verdict": "probably"}') is None and lc.parse_verdict("no json") is None
    assert lc.drawn(["a", "b", "c"]) == lc.drawn(["c", "a", "b"])
    items = ([{"role": "population", "verdict": v, "type": "Rule", "scope": "org", "checkable": True}
              for v in ("stale", "current", "current", "no claim")]
             + [{"role": "population", "type": "Rule", "scope": "org", "error": "timed out"},
                {"role": "negative", "verdict": "stale"}, {"role": "positive", "verdict": "stale"},
                {"role": "positive", "verdict": "current"}])
    s = lc.summarize(items)
    assert s["stale_rate"]["stale"] == 1 and s["stale_rate"]["decided"] == 3
    assert s["claim_share"] == {"claims": 3, "of": 5} and s["invalid_share"] == 0.2
    assert (s["negatives_called_stale"], s["positives_called_stale"], s["stale_checkable"]) == (1, 1, 1)
