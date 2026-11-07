"""A lesson last checked on another branch is reported as such, not as nonsense (#126).

One local store serves every branch. A lesson verified on branch B carries B's commit
when drift runs on branch A. If the governed files still match that commit, the check
passed on the same content A has, so it is not drift, but its evidence depends on B.
If they differ, it is drift, and the reason used to be built from times that can
contradict each other ("changed 10-07, after its last check on 10-08").
"""
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from okl import core, drift
from okl.store import Node

SRC = str(Path(__file__).resolve().parents[1] / "src")


@pytest.fixture
def branches(tmp_path):
    """main, plus two side branches: one leaves g.py as main has it, one changes it."""
    repo = tmp_path / "r"; repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]

    def run(*a):
        return subprocess.run([*git, *a], capture_output=True, text=True, check=True).stdout.strip()

    def commit(path, text):
        (repo / path).write_text(text)
        run("add", path)
        run("commit", "-qm", f"edit {path}")
        return run("rev-parse", "HEAD")

    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    base = commit("g.py", "the rule holds\n")
    commit("other.txt", "main\n")
    run("switch", "-qc", "same")
    same = commit("other.txt", "side\n")            # g.py untouched
    run("switch", "-q", "main")
    run("switch", "-qc", "differ")
    differ = commit("g.py", "changed on a side branch\n")
    run("switch", "-q", "main")
    return {"repo": repo, "run": run, "commit": commit, "base": base, "same": same, "differ": differ}


def _lesson(nid, commit):
    """A lesson stamped exactly as `okl verify` stamps one, on `commit`."""
    now = _dt.datetime.now(_dt.UTC)
    return Node(type="Rule", title=nid, scope="repo:r", files="g.py",
                verified_at=int(now.timestamp() * 1000),
                verified_by=f"`true` exit 0, matched '' on commit {commit} @ "
                            + now.strftime("%Y-%m-%dT%H:%MZ"),
                verified_commit=commit, id=nid)


def test_the_ancestry_predicate(branches):
    """True on this branch's history, False on a sibling's, None when git cannot say."""
    rd = str(branches["repo"])
    assert drift._on_this_branch(branches["base"], rd) is True
    assert drift._on_this_branch(branches["same"], rd) is False
    assert drift._on_this_branch("0" * 40, rd) is None          # well formed, not in this clone
    assert drift._on_this_branch("not-a-commit", rd) is None
    assert drift._on_this_branch(None, rd) is None


def test_the_gate_reports_off_branch_drift_with_a_reason_that_says_so(branches):
    """Files that differ from another branch's commit are drift, and the reason names
    the commit instead of two dates; files that still match are not drift."""
    rd = str(branches["repo"])
    nodes = [_lesson("on", branches["base"]), _lesson("same", branches["same"]),
             _lesson("differ", branches["differ"])]

    hits, checked = drift.scan_drift(nodes, "r", rd)

    assert checked == 3
    assert [h.node_id for h in hits] == ["differ"]
    assert "outside this branch's history" in hits[0].reason
    assert branches["differ"][:7] in hits[0].reason


def test_off_branch_lists_every_lesson_whose_evidence_lives_on_another_branch(branches):
    """Drifted or not, their evidence lives on another branch; a snapshot written here
    holds those stamps back (#378), so the list is where they are named."""
    rd = str(branches["repo"])
    nodes = [_lesson("on", branches["base"]), _lesson("same", branches["same"]),
             _lesson("differ", branches["differ"])]

    found = drift.off_branch(nodes, "r", rd)

    assert sorted(n.id for n, _c in found) == ["differ", "same"]
    text = drift.render_off_branch([(n, c) for n, c in found if n.id == "same"])
    assert "[same]" in text and branches["same"][:7] in text and "okl reverify" in text
    assert drift.render_off_branch([]) == ""


def test_a_snapshot_written_here_takes_no_stamp_from_another_branch(branches):
    """One store serves every branch, so a lesson verified on a side branch carried that
    branch's commit into the snapshot written on main, and main's gate judged g.py against a
    commit whose g.py differs (#378). Written here, such a lesson keeps the entry this branch
    committed, or is left out; written on the side branch, it carries that branch's stamp."""
    # ARRANGE — "kept" has an entry committed here, from a check on main; "new" has none;
    # both were last verified on the branch that changes g.py
    rd, base, differ = str(branches["repo"]), branches["base"], branches["differ"]
    nodes = [_lesson("on", base), _lesson("kept", differ), _lesson("new", differ)]
    entry = drift.snapshot([_lesson("kept", base)], "r")["rules"][0]
    committed = {"format": drift.SNAPSHOT_FORMAT, "repo": "r", "rules": [entry]}

    # ACT — written on main
    here = {r["id"]: r for r in drift.branch_snapshot(nodes, "r", rd, committed)["rules"]}

    # ASSERT (1) — this branch's stamp as is; this branch's entry kept; the rest left out
    assert here["on"]["verified_commit"] == base
    assert here["kept"] == entry
    assert "new" not in here
    # (2) — so main's gate, reading that snapshot, has nothing to report
    rules, problems = drift.nodes_from_snapshot({"format": drift.SNAPSHOT_FORMAT, "repo": "r",
                                                 "rules": list(here.values())})
    assert problems == [] and drift.scan_drift(rules, "r", rd)[0] == []

    # ACT / ASSERT (3) — written on the side branch, its own stamps go in
    branches["run"]("switch", "-q", "differ")
    there = {r["id"]: r for r in drift.branch_snapshot(nodes, "r", rd, committed)["rules"]}
    assert there["kept"]["verified_commit"] == differ and there["new"]["verified_commit"] == differ
    assert "on" in there   # main's commit is in the side branch's history too


def test_the_briefing_mark_says_where_the_check_ran(branches):
    """The briefing's verdict comes from the same predicate as the gate's, and its mark
    no longer prints a change date older than the check it claims came after."""
    rd = str(branches["repo"])
    rules = []
    for nid in ("same", "differ"):
        n = _lesson(nid, branches[nid])
        rules.append({"id": n.id, "title": n.title, "scope": n.scope, "files": n.files,
                      "verified_at": n.verified_at, "verified_by": n.verified_by,
                      "verified_commit": n.verified_commit})
    result = {"rules": rules}

    assert drift.annotate_briefing(result, "r", rd) == 1
    marks = {r["id"]: r.get("drift") for r in result["rules"]}
    assert marks["same"] is None
    assert marks["differ"]["reason"] == "verified on another branch"
    assert marks["differ"]["commit"] == branches["differ"][:7]
    tag = core._drift_tag({"id": "differ", "drift": marks["differ"]})
    assert "another branch" in tag and branches["differ"][:7] in tag
    assert "after its last check" not in tag


@pytest.mark.parametrize("mark", [
    {"files": "g.py", "reason": "never verified"},
    {"files": "g.py", "changed": "2026-10-01", "reason": "verified with no observed check"},
    {"files": "g.py", "changed": "2026-10-01", "verified": "2026-09-01",
     "reason": "changed since last verified"},
    {"files": "g.py", "changed": "2026-10-01", "verified": "2026-10-02",
     "reason": "verified on another branch", "commit": "abc1234"},
])
def test_every_drift_verdict_renders(mark):
    """Each verdict carries different fields. 'verified with no observed check' has no
    verification date, and rendering one raised KeyError: 'verified', so a briefing that
    held such a lesson could not be printed at all."""
    tag = core._drift_tag({"id": "x", "drift": mark})
    assert tag.startswith(" *(") and tag.endswith(")*")
    briefing = core.render_check_for_agent({
        "repo": "r", "task": "t", "match_count": 1, "dropped_by_cutoff": 0,
        "next_actions": [{"kind": "apply_fix", "target": "a rule", "id": "x", "how": "do it",
                          "drift": mark}],
        "rules": [{"id": "x", "title": "a rule", "fix": "do it", "drift": mark}],
    })
    assert "a rule" in briefing


def test_cli_warns_gates_and_reverify_restamps_an_off_branch_lesson(branches, tmp_path):
    """End to end: verify on a side branch, come back to main, and every command that
    writes or reads the snapshot says so; `okl reverify` settles it."""
    repo, run = branches["repo"], branches["run"]
    env = {**os.environ, "PYTHONPATH": SRC, "HOME": str(tmp_path)}
    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        env.pop(k, None)

    def okl(*a):
        return subprocess.run([sys.executable, "-m", "okl", *a], cwd=repo, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    # ARRANGE — a lesson about g.py, checked on a side branch where g.py matches main
    assert okl("init", "--repo", "r", "--no-seed", "--no-claude").returncode == 0

    def record(title: str) -> str:
        # Failed once in a full suite, as an IndexError on empty stdout that hid the cause
        # (0.11.0 release prep): say what record printed when it does not record.
        r = okl("record", "--type", "Rule", "--scope", "repo", "--title", title, "--files", "g.py")
        assert r.returncode == 0 and r.stdout.strip(), f"exit {r.returncode}: {r.stderr}"
        return r.stdout.strip().splitlines()[-1]

    lid, other = record("the rule holds"), record("another rule")
    check = ("grep -q holds g.py && echo HOLDS", "HOLDS")
    run("switch", "-q", "same")
    assert okl("verify", lid, "--run", check[0], "--expect", check[1]).returncode == 0
    run("switch", "-q", "main")

    # ACT / ASSERT (1) — verifying another lesson here names the one checked elsewhere
    r = okl("verify", other, "--run", check[0], "--expect", check[1])
    assert r.returncode == 0 and f"[{lid}]" in r.stderr and "outside this branch" in r.stderr, r.stderr
    assert f"[{other}]" not in r.stderr

    # (2) export --drift names it and leaves it out: main committed no entry for it to keep,
    # and a stamp from another branch is not this branch's to commit (#378). The store's gate
    # passes (files match) and lists it; the snapshot's gate never sees it
    r = okl("export", "--drift")
    assert r.returncode == 0 and f"[{lid}]" in r.stderr and "not in okl-drift.json" in r.stderr, r.stderr
    assert lid not in {e["id"] for e in json.loads((repo / "okl-drift.json").read_text())["rules"]}
    run("add", "okl-drift.json"); run("commit", "-qm", "snapshot")
    r = okl("drift", "--gate")
    assert r.returncode == 0 and f"[{lid}]" in r.stdout and branches["same"][:7] in r.stdout, r.stdout
    r = okl("drift", "--gate", "--snapshot", "okl-drift.json")
    assert r.returncode == 0 and f"[{lid}]" not in r.stdout, (r.stdout, r.stderr)
    listed = json.loads(okl("drift", "--format", "json").stdout)["off_branch"]
    assert [e["node_id"] for e in listed] == [lid]

    # (3) reverify re-checks it here, though it had not drifted, and the warning is gone
    r = okl("reverify", "--yes")
    assert r.returncode == 0 and "1 re-verified" in r.stdout, (r.stdout, r.stderr)
    assert json.loads(okl("drift", "--format", "json").stdout)["off_branch"] == []


def test_export_on_a_branch_keeps_its_entry_for_a_lesson_verified_on_another(branches, tmp_path):
    """The field report's case, end to end (#378): a lesson checked on main and committed in
    main's snapshot is checked again on a branch that changes its file. Back on main, export
    wrote that branch's stamp, and main's gate went red for a lesson main never touched."""
    repo, run = branches["repo"], branches["run"]
    env = {**os.environ, "PYTHONPATH": SRC, "HOME": str(tmp_path)}
    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        env.pop(k, None)

    def okl(*a):
        return subprocess.run([sys.executable, "-m", "okl", *a], cwd=repo, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    # ARRANGE — verified and committed on main
    assert okl("init", "--repo", "r", "--no-seed", "--no-claude").returncode == 0
    r = okl("record", "--type", "Rule", "--scope", "repo", "--title", "g.py exists", "--files", "g.py")
    assert r.returncode == 0, r.stderr
    lid = r.stdout.strip().splitlines()[-1]
    check = ("test -f g.py && echo PRESENT", "PRESENT")
    assert okl("verify", lid, "--run", *check[:1], "--expect", check[1]).returncode == 0
    assert okl("export", "--drift").returncode == 0
    run("add", "okl-drift.json"); run("commit", "-qm", "snapshot on main")
    on_main = json.loads((repo / "okl-drift.json").read_text())["rules"][0]

    # ACT (1) — verified again on the branch that changes g.py, and exported there
    run("switch", "-q", "differ")
    assert okl("verify", lid, "--run", *check[:1], "--expect", check[1]).returncode == 0
    assert okl("export", "--drift").returncode == 0
    # ASSERT (1) — that branch's snapshot carries that branch's stamp
    assert json.loads((repo / "okl-drift.json").read_text())["rules"][0]["verified_commit"] == branches["differ"]
    run("add", "okl-drift.json"); run("commit", "-qm", "snapshot on the side branch")

    # ACT (2) — back on main, export again
    run("switch", "-q", "main")
    r = okl("export", "--drift")

    # ASSERT (2) — main's entry kept, the lesson named, and main's gate green
    assert r.returncode == 0, r.stderr
    assert f"[{lid}]" in r.stderr and "keeps this branch's entry" in r.stderr, r.stderr
    assert json.loads((repo / "okl-drift.json").read_text())["rules"] == [on_main]
    run("add", "okl-drift.json")
    if run("diff", "--cached", "--name-only"):
        run("commit", "-qm", "snapshot on main again")
    r = okl("drift", "--gate", "--snapshot", "okl-drift.json")
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_an_untracked_snapshot_from_another_branch_lends_no_entry(branches, tmp_path):
    """An untracked okl-drift.json survives a branch switch with the stamps it was written
    with. Where this branch has committed none, the refresh used to fall back to that file;
    for a lesson last verified elsewhere it must keep only what HEAD committed (#378)."""
    repo, run = branches["repo"], branches["run"]
    env = {**os.environ, "PYTHONPATH": SRC, "HOME": str(tmp_path)}
    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        env.pop(k, None)

    def okl(*a):
        return subprocess.run([sys.executable, "-m", "okl", *a], cwd=repo, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    # ARRANGE — verified on the side branch, its snapshot written there and left untracked
    assert okl("init", "--repo", "r", "--no-seed", "--no-claude").returncode == 0
    lid = okl("record", "--type", "Rule", "--scope", "repo", "--title", "g.py exists",
              "--files", "g.py").stdout.strip().splitlines()[-1]
    run("switch", "-q", "differ")
    assert okl("verify", lid, "--run", "test -f g.py && echo PRESENT", "--expect", "PRESENT").returncode == 0
    assert okl("export", "--drift").returncode == 0
    run("switch", "-q", "main")
    assert (repo / "okl-drift.json").exists() and not run("ls-files", "okl-drift.json")

    # ACT — export on main, which has committed no snapshot
    r = okl("export", "--drift")

    # ASSERT — the side branch's stamp is not carried over from the untracked file. That
    # empties the snapshot, so export refuses it as ever, but says why: the store does hold a
    # rule that governs files, and it is named
    written = json.loads((repo / "okl-drift.json").read_text())["rules"]
    assert lid not in {e["id"] for e in written}, written
    assert r.returncode == 2 and "last verified on another branch" in r.stderr, r.stderr
    assert "no rule in this store governs files" not in r.stderr and f"[{lid}]" in r.stderr, r.stderr
