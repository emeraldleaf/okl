"""Triggers and the calibrated briefing decision (#291, REPORT §4w)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from okl import core, decide
from okl.client import decision_setting
from okl.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _okl(tmp_path: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI against a throwaway store under tmp_path."""
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_SERVICE_URL", "OKL_TOKEN", "OKL_DECISION")}
    env["OKL_DATABASE_URL"] = f"sqlite:///{tmp_path / 'store.db'}"
    env["PYTHONPATH"] = str(ROOT / "src")
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "okl", *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True)


def test_record_update_and_show_carry_triggers(tmp_path):
    """`--trigger` is repeatable on record, replaces on update, clears with an empty value, and
    `okl show` lists them; full-text search finds a lesson by a word only its triggers hold."""
    r = _okl(tmp_path, "record", "--type", "Rule", "--title", "token storage", "--scope", "org",
             "--trigger", "users get logged out whenever they reload the page",
             "--trigger", "where should the bearer credential live in the SPA", "--id", "t1")
    assert r.returncode == 0, r.stdout + r.stderr
    shown = json.loads(_okl(tmp_path, "show", "t1", "--format", "json").stdout)
    assert shown["triggers"] == ("users get logged out whenever they reload the page\n"
                                 "where should the bearer credential live in the SPA")
    assert "    - users get logged out whenever they reload the page" in _okl(tmp_path, "show", "t1").stdout
    found = json.loads(_okl(tmp_path, "search", "bearer", "--format", "json").stdout)
    assert [x["id"] for x in found] == ["t1"]

    u = _okl(tmp_path, "update", "t1", "--trigger", "session lost after a refresh")
    assert u.returncode == 0, u.stdout + u.stderr
    assert json.loads(_okl(tmp_path, "show", "t1", "--format", "json").stdout)["triggers"] == "session lost after a refresh"
    u = _okl(tmp_path, "update", "t1", "--trigger", "")
    assert u.returncode == 0, u.stdout + u.stderr
    assert not json.loads(_okl(tmp_path, "show", "t1", "--format", "json").stdout).get("triggers")


def test_a_pack_writes_triggers_as_a_list_and_an_empty_list_clears():
    """A seed pack writes `triggers` as a list; core joins it one per line, and an empty list
    on update is an explicit clear, as for aliases."""
    s = Store("sqlite:///:memory:")
    try:
        a = core.record(s, type="Rule", title="t", scope="org", triggers=["add retries", "  the job   hangs "])
        assert s.get_node(a).triggers == "add retries\nthe job hangs"
        core.update(s, a, triggers=[])
        assert not s.get_node(a).triggers
    finally:
        s.close()


def _store_with(lessons: list[dict]) -> Store:
    s = Store("sqlite:///:memory:")
    for i, lesson in enumerate(lessons):
        core.record(s, type="Rule", scope="org", id=f"r{i}", **lesson)
    return s


def test_the_calibrated_decision_briefs_what_shares_the_subject_and_nothing_else():
    """A lesson whose about-text holds three of the prompt's subject words is briefed; one
    sharing a single word is not; a prompt with no subject, and one a harness wrote, get
    nothing; the floor stays the default."""
    s = _store_with([
        {"title": "retry the uploader with backoff",
         "triggers": ["uploads to the bucket fail intermittently and the job gives up"]},
        {"title": "uploader logging format"},
        {"title": "unrelated rule about pagination"},
    ])
    try:
        task = "the uploader job gives up when bucket uploads fail intermittently"
        res = core.check(s, repo="r", task=task, decision="calibrated")
        assert core.briefed_ids(res) == ["r0"]
        assert res["decision"] == "calibrated" and res["weak_matches"] >= 1
        # The default is still the floor, which keeps its own behaviour.
        assert core.check(s, repo="r", task=task)["decision"] == "floor"
        assert core.briefed_ids(core.check(s, repo="r", task="ok do it", decision="calibrated")) == []
        harness = core.check(s, repo="r", decision="calibrated",
                             task="<task-notification> uploader job bucket uploads fail </task-notification>")
        assert core.briefed_ids(harness) == [] and harness["skipped"] == "harness"
        floor_harness = core.check(s, repo="r", task="<agent-message from=x> uploader bucket uploads </agent-message>")
        assert core.briefed_ids(floor_harness) == [] and floor_harness["skipped"] == "harness"
    finally:
        s.close()


def test_the_calibrated_decision_briefs_at_most_the_cap():
    """Seven lessons that all clear the line yield CALIBRATED_CAP, best first."""
    s = _store_with([{"title": f"cache invalidation stale reads replica lag {i}"} for i in range(7)])
    try:
        res = core.check(s, repo="r", task="stale reads after cache invalidation with replica lag",
                         decision="calibrated")
        assert len(core.briefed_ids(res)) == decide.CALIBRATED_CAP
    finally:
        s.close()


def test_two_rare_shared_words_clear_the_line_and_two_common_ones_do_not():
    """The line is three shared words, or two whose summed rarity reaches 8: two words that
    are in nearly every record are not enough on their own."""
    filler = [{"title": f"service config note {i}", "body": "service config"} for i in range(30)]
    s = _store_with([{"title": "pkce verifier for public clients"},
                     {"title": "service config for the gateway"}, *filler])
    try:
        rare = core.check(s, repo="r", task="pkce verifier missing", decision="calibrated")
        assert "r0" in core.briefed_ids(rare)
        common = core.check(s, repo="r", task="service config question", decision="calibrated")
        assert core.briefed_ids(common) == []
    finally:
        s.close()


def test_the_decision_setting_reads_env_over_config_and_refuses_unknown_values():
    """OKL_DECISION wins over the config, an empty value falls through, and an unknown one is refused."""
    assert decision_setting(None, None) == "floor"
    assert decision_setting(None, "calibrated") == "calibrated"
    assert decision_setting("calibrated", "floor") == "calibrated"
    assert decision_setting("", "calibrated") == "calibrated"
    with pytest.raises(ValueError, match="decision"):
        decision_setting("strict", None)
    with pytest.raises(ValueError, match="decision"):
        core.check(Store("sqlite:///:memory:"), repo="r", task="x", decision="strict")


def test_check_follows_the_decision_flag_and_env(tmp_path):
    """`okl check --decision calibrated` and OKL_DECISION both reach core.check."""
    r = _okl(tmp_path, "record", "--type", "Rule", "--title", "uploader retries with backoff", "--scope", "org",
             "--trigger", "uploads fail intermittently and the job gives up", "--id", "u1")
    assert r.returncode == 0, r.stdout + r.stderr
    flag = json.loads(_okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "json",
                           "--decision", "calibrated", "--task", "the uploader job gives up on failed uploads").stdout)
    assert flag["decision"] == "calibrated" and [x["id"] for x in flag["rules"]] == ["u1"]
    env = json.loads(_okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "json",
                          "--task", "the uploader job gives up on failed uploads",
                          env_extra={"OKL_DECISION": "calibrated"}).stdout)
    assert env["decision"] == "calibrated"
