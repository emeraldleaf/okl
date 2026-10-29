"""The index arm (REPORT §4r): every other lesson in scope as id and title, so an agent can fetch
what the briefing did not select; and the harness pieces that count whether it did."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from okl import core
from okl.store import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store():
    """A fresh in-memory store, closed after the test."""
    s = Store("sqlite:///:memory:")
    yield s
    s.close()


def test_the_index_lists_every_other_live_lesson_in_scope(store):
    """The briefed lessons are not repeated; retired ones and other repos' ones are not listed;
    the rest appear by title, and the agent-format briefing prints them with the fetch hint."""
    a = core.record(store, type="Rule", title="token storage", scope="org",
                    symptom="an access token written to web storage")
    b = core.record(store, type="Rule", title="pagination", scope="org", symptom="an offset query")
    core.record(store, type="Rule", title="other repo's quirk", scope="repo:other")
    r = core.record(store, type="Rule", title="retired", scope="org")
    core.retire(store, r, "wrong")
    res = core.check(store, repo="r", task="an access token written to web storage", index=True)
    assert [x["id"] for x in res["rules"]] == [a]
    assert [e["id"] for e in res["index"]] == [b]
    text = core.render_check_for_agent(res)
    assert "Every other lesson in scope (1)" in text and f"- [{b}] pagination" in text and "okl show <id>" in text
    assert "index" not in core.check(store, repo="r", task="an access token written to web storage")
    # The index names lessons; it does not show them, so the exposure log must not count them.
    assert core.briefed_ids(res) == [a]


def test_near_misses_name_what_matched_and_was_left_out(store):
    """The near-miss list (REPORT §4s) holds the records the floor or the cutoff left out, in
    rank order, never a briefed one, at most NEAR_MISSES; the agent format prints it."""
    kept = core.record(store, type="Rule", title="orders endpoint ownership", scope="org",
                       symptom="an orders endpoint fetches by id with no owner check")
    weak = core.record(store, type="Rule", title="pagination caps", scope="org",
                       body="every list endpoint paginates")      # shares one word, outside the subject
    res = core.check(store, repo="r", task="add an orders endpoint that fetches one order by id for the owner",
                     near_misses=True)
    assert [x["id"] for x in res["rules"]] == [kept]
    assert res["near_misses"] == [{"id": weak, "title": "pagination caps"}]
    text = core.render_check_for_agent(res)
    assert "Near misses (1)" in text and f"- [{weak}] pagination caps" in text
    assert "near_misses" not in core.check(store, repo="r", task="add an orders endpoint for the owner")
    assert core.briefed_ids(res) == [kept]
    # Drift marks on a near miss are not exposure either (review on #270).
    res["near_misses"][0]["drift"] = {"reason": "never verified", "files": "x"}
    assert core.drifted_ids(res) == []
    # When nothing passed the floor, the briefing points at the near misses, not a clean slate.
    none = core.check(store, repo="r", task="paginate the admin list", near_misses=True)
    assert none["rules"] == [] and none["near_misses"]
    assert "clean slate" not in core.render_check_for_agent(none) and "came closest" in core.render_check_for_agent(none)


def test_a_remote_check_that_drops_the_near_misses_is_refused(monkeypatch):
    """An older service answers an ordinary briefing to a request it does not understand; the
    client must not read that as "no near misses" (review on #270)."""
    from okl.client import Client, OKLRejectedError
    c = Client(config={"repo": "r", "service_url": "http://service.invalid"})
    monkeypatch.setattr(c, "_post", lambda path, body: {"repo": "r", "task": body["task"], "rules": [], "match_count": 0})
    monkeypatch.setattr("okl.client.drift.annotate_briefing", lambda *a, **k: None)
    assert c.check("a task")["match_count"] == 0            # nothing asked for: fine
    c.near_misses = True
    with pytest.raises(OKLRejectedError, match="near_misses"):
        c.check("a task")
    monkeypatch.setattr(c, "_post", lambda path, body: {"repo": "r", "task": body["task"], "rules": [], "match_count": 0, "near_misses": None})
    with pytest.raises(OKLRejectedError, match="near_misses"):   # a null is not the list asked for
        c.check("a task")
    monkeypatch.setattr(c, "_post", lambda path, body: {"repo": "r", "task": body["task"], "rules": [], "match_count": 0, "near_misses": []})
    assert c.check("a task")["near_misses"] == []


def test_okl_check_index_flag_appends_the_index(tmp_path):
    """`okl check --index` carries the index in the JSON and the agent format."""
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_SERVICE_URL", "OKL_TOKEN")}
    env["OKL_DATABASE_URL"] = f"sqlite:///{tmp_path / 'store.db'}"
    def okl(*args):
        return subprocess.run([sys.executable, "-m", "okl", *args], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert okl("record", "--type", "Rule", "--title", "pagination", "--scope", "org", "--id", "p").returncode == 0
    out = json.loads(okl("check", "--repo", "r", "--interests", "", "--format", "json", "--index", "--task", "add a login form").stdout)
    assert out["index"] == [{"id": "p", "title": "pagination"}]
    near = json.loads(okl("check", "--repo", "r", "--interests", "", "--format", "json", "--near-misses",
                          "--task", "pagination of the login list page").stdout)
    assert "near_misses" in near
    assert "- [p] pagination" in okl("check", "--repo", "r", "--interests", "", "--index", "--task", "add a login form").stdout


@pytest.fixture
def ab():
    """evals/ab_harness.py as a module."""
    spec = importlib.util.spec_from_file_location("ab_harness", ROOT / "evals" / "ab_harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_shim_counts_a_fetch_only_when_okl_show_succeeded(ab, tmp_path):
    """The generator's `okl` shim runs the real okl and logs its exit status with the
    arguments; a show that failed is an attempt, not a lesson read (review on #269)."""
    ab.write_shim(str(tmp_path))
    log = str(tmp_path / "shim.log")
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_SERVICE_URL", "OKL_TOKEN")}
    env.update(OKL_SHIM_LOG=log, PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
               OKL_DATABASE_URL=f"sqlite:///{tmp_path / 'store.db'}")
    assert subprocess.run([sys.executable, "-m", "okl", "record", "--type", "Rule", "--title", "t", "--scope", "org", "--id", "t1"],
                          env=env, capture_output=True, text=True, cwd=tmp_path).returncode == 0
    ok = subprocess.run(["okl", "show", "t1", "--format", "json"], env=env, capture_output=True, text=True, cwd=tmp_path)
    bad = subprocess.run(["okl", "show", "nope"], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert ok.returncode == 0 and json.loads(ok.stdout)["id"] == "t1" and bad.returncode != 0
    assert ab.fetched_ids(log) == ["t1"]
    assert ab.fetched_ids(str(tmp_path / "missing.log")) == []


def test_run_one_records_what_the_generator_fetched(ab, monkeypatch, tmp_path):
    """With tools allowed, a sample carries the fetched ids and whether the governing one was read."""
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    task = {"id": "t/paraphrase", "task": "do the thing", "signal": "s", "defect_node": "seed:p:gov"}
    seen = {}

    def fake_call(cmd, prompt, timeout, workdir, env=None):
        if "--allowedTools" in cmd:                       # the generator
            seen["env"] = env
            Path(env["OKL_SHIM_LOG"]).write_text("0 show seed:p:gov --format json\n0 show seed:p:other\n2 show seed:p:failed\n")
            return "def f(): return 1"
        return json.dumps({"implemented": True, "defect_reproduced": False, "reason": "clean"})
    monkeypatch.setattr(ab, "call", fake_call)
    rec, ok = ab.run_one(task, "indexed", 0, briefed_header=None, brief_err="", timeout=5,
                         workdir=str(tmp_path), indexed_header="BRIEFING\n")
    assert ok and rec["fetched"] == ["seed:p:gov", "seed:p:other"] and rec["fetched_governing"] is True
    assert seen["env"]["PATH"].startswith(str(tmp_path / "bin")) and seen["env"]["OKL_BRIEFING_LOG"] == "0"
    # An arm whose header is missing fails closed, as the briefed arm always has.
    rec, ok = ab.run_one(task, "indexed", 1, briefed_header="B", brief_err="no index", timeout=5,
                         workdir=str(tmp_path), indexed_header=None)
    assert not ok and "fail closed" in rec["error"]


def test_arms_are_a_subset_named_once(ab):
    """`--arms` takes each arm at most once; a repeat would run and count twice."""
    import argparse
    assert ab.parse_arms("baseline,indexed") == ["baseline", "indexed"]
    for bad in ("baseline,indexed,indexed", "briefed,reranked", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            ab.parse_arms(bad)


def test_generator_cmd_carries_the_allowed_tools(ab, monkeypatch):
    """The allowed tools reach the generator as claude -p's flag, quoted as one word."""
    assert ab.generator_cmd() == ab.GENERATOR_CMD
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    assert ab.generator_cmd().endswith("--allowedTools 'Bash(okl show:*)'")
