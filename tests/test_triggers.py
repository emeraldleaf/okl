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
    nothing. The default, tiered, briefs the same lesson and names the one-word match in a line
    (§4y)."""
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
        tiered = core.check(s, repo="r", task=task)
        assert tiered["decision"] == "tiered" and core.briefed_ids(tiered) == ["r0"]
        assert [e["id"] for e in tiered["also_matched"]] == ["r1"]
        assert core.briefed_ids(core.check(s, repo="r", task="ok do it", decision="calibrated")) == []
        harness = core.check(s, repo="r", decision="calibrated",
                             task="<task-notification> uploader job bucket uploads fail </task-notification>")
        assert core.briefed_ids(harness) == [] and harness["skipped"] == "harness"
        floor_harness = core.check(s, repo="r", decision="floor",
                                   task="<agent-message from=x> uploader bucket uploads </agent-message>")
        assert core.briefed_ids(floor_harness) == [] and floor_harness["skipped"] == "harness"
    finally:
        s.close()


def test_the_calibrated_decision_briefs_at_most_the_cap():
    """Seven lessons that all clear the line yield CALIBRATED_CAP, best first; the two the cap
    leaves out are counted as cut, not as below the line."""
    s = _store_with([{"title": f"cache invalidation stale reads replica lag {i}"} for i in range(7)])
    try:
        res = core.check(s, repo="r", task="stale reads after cache invalidation with replica lag",
                         decision="calibrated")
        assert len(core.briefed_ids(res)) == decide.CALIBRATED_CAP
        assert res["dropped_by_cutoff"] == 7 - decide.CALIBRATED_CAP and res["weak_matches"] == 0
    finally:
        s.close()


def test_the_tiered_decision_names_what_the_cap_cuts_and_what_the_floor_keeps():
    """Tiered shows what clears the line, at most the cap, and names the rest in one line each:
    the two the cap cut first, then a lesson only the floor keeps; none is cut or counted weak,
    and a lesson sharing no word is not named (REPORT §4y)."""
    s = _store_with([*({"title": f"cache invalidation stale reads replica lag {i}"} for i in range(7)),
                     {"title": "failover runbook for the primary"}, {"title": "pagination cursor format"}])
    try:
        res = core.check(s, repo="r", task="stale reads after cache invalidation with replica lag during failover")
        shown = core.briefed_ids(res)
        also = [e["id"] for e in res["also_matched"]]
        assert len(shown) == decide.CALIBRATED_CAP
        assert sorted(also[:2]) == sorted({f"r{i}" for i in range(7)} - set(shown))
        assert also[2:] == ["r7"]
        assert res["dropped_by_cutoff"] == 0
        assert res["weak_matches"] == 0
    finally:
        s.close()


def test_the_lessons_shown_in_full_do_not_use_up_the_second_tiers_places():
    """At --limit 3, three lessons shown in full that are also the floor's first three left the
    second tier empty while a fourth matched; the floor is now asked for the limit beyond what
    is shown (review on #299)."""
    s = _store_with([*({"title": f"webhook signature verification replay window {i}"} for i in range(3)),
                     {"title": "rotate the webhook secret"}])
    try:
        res = core.check(s, repo="r", task="verify the webhook signature and the replay window", limit=3)
        assert len(core.briefed_ids(res)) == 3
        assert [e["id"] for e in res["also_matched"]] == ["r3"]
    finally:
        s.close()


def test_a_withdrawn_lesson_in_the_second_tier_is_a_warning_not_a_fix():
    """A retracted rule the floor keeps is named as something to avoid, without its old fix,
    as the full briefing routes it (review on #299)."""
    s = Store("sqlite:///:memory:")
    core.record(s, type="Rule", scope="org", id="old", title="cache the session token in local storage",
                fix="Write the token to localStorage on login.", status="retracted")
    try:
        res = core.check(s, repo="r", task="where should the session token live")
        entry = next(e for e in res["also_matched"] if e["id"] == "old")
        assert entry["avoid"] == "retracted"
        assert entry["fix"] == ""
        line = core._also_line(entry)
        assert line == "- [old] AVOID (retracted): cache the session token in local storage"
        assert "localStorage" not in core.render_check_for_agent(res)
    finally:
        s.close()


def test_the_action_list_does_not_deny_a_lesson_shown_in_full():
    """A rule shown in full with no fix routes no action; with the second tier non-empty the
    action list said "no rule matched closely", against the full briefing (review on #299)."""
    s = _store_with([{"title": "webhook signature verification replay window"},
                     {"title": "rotate the webhook secret", "fix": "Rotate it every ninety days."}])
    try:
        res = core.check(s, repo="r", task="verify the webhook signature and the replay window")
        assert res["match_count"] == 1
        assert res["also_matched"]
        compact = core.render_actions_only(res)
        assert "no rule matched" not in compact
        assert compact.startswith("OKL: 1 lesson(s) matched with no action to route")
    finally:
        s.close()


def test_the_action_list_does_not_deny_a_lesson_shown_in_full_when_nothing_else_matched():
    """The same rule with no second tier at all: the action list said "no encoded rule applies
    ... Proceed." while the full briefing showed it (review on #299)."""
    s = _store_with([{"title": "webhook signature verification replay window"}])
    try:
        res = core.check(s, repo="r", task="verify the webhook signature and the replay window")
        assert res["match_count"] == 1
        assert res["also_matched"] == []
        compact = core.render_actions_only(res)
        assert "no encoded rule applies" not in compact
        assert compact.startswith("OKL: 1 lesson(s) matched with no action to route")
    finally:
        s.close()


def test_a_service_that_predates_tiered_answers_by_calibrated_instead_of_refusing(monkeypatch):
    """A service that knows `decision` but not "tiered" refuses it with a 422; the client asks
    again with the previous default and says which decision answered, rather than block every
    prompt. Any other refusal stands (review on #299)."""
    from okl.client import Client, OKLRejectedError
    c = Client(config={"repo": "r", "service_url": "http://service.invalid"})
    monkeypatch.setattr("okl.client.drift.annotate_briefing", lambda *a, **k: None)
    sent = []

    def older_service(path, body):
        sent.append(body["decision"])
        if body["decision"] == "tiered":
            raise OKLRejectedError("OKL service rejected the request (422): [{'loc': ['body', 'decision'], "
                                   "'msg': \"Input should be 'floor' or 'calibrated'\", 'input': 'tiered'}]", status=422)
        return {"repo": "r", "task": body["task"], "rules": [], "match_count": 0, "decision": body["decision"]}

    monkeypatch.setattr(c, "_post", older_service)
    res = c.check("a task")
    assert sent == ["tiered", "calibrated"]
    assert res["decision"] == "calibrated"
    assert "upgrade the service" in res["decision_unavailable"]

    def refuses(path, body):
        raise OKLRejectedError("OKL service rejected the request (401): missing token", status=401)

    monkeypatch.setattr(c, "_post", refuses)
    with pytest.raises(OKLRejectedError, match="401"):
        c.check("a task")


def test_a_stale_lesson_in_the_second_tier_is_marked_for_re_verification():
    """A lesson past its TTL is named with the full briefing's stale tag, so its fix is not
    read as current (review on #299)."""
    from okl.store import Node
    old = Node(id="s", type="Rule", scope="org", title="pin the base image", fix="Pin it by digest.",
               ttl_days=1, verified_at=1, created_at=1)
    entry = core._also_entry(old)
    assert entry["stale"] is True
    assert core._also_line(entry) == "- [s] pin the base image *(STALE — re-verify)* — Pin it by digest."
    fresh = core._also_entry(Node(id="f", type="Rule", scope="org", title="t", fix="Do it."))
    assert "stale" not in fresh


def test_a_second_tier_line_carries_the_first_sentence_of_the_fix_cut_at_a_word():
    """A line is the title and the first sentence of the fix, at most ALSO_FIX_CHARS of it,
    cut at a word; a lesson with no fix is its title alone."""
    from okl.store import Node
    short = core._also_entry(Node(id="a", type="Rule", scope="org", title="t", fix="Do this. Then that."))
    assert short["fix"] == "Do this."
    long = core._also_entry(Node(id="b", type="Rule", scope="org", title="t", fix="word " * 60))
    assert long["fix"].endswith("…")
    assert len(long["fix"]) <= core.ALSO_FIX_CHARS + 1
    assert core._also_line(core._also_entry(Node(id="c", type="Rule", scope="org", title="t"))) == "- [c] t"


def test_the_second_tier_is_rendered_for_the_agent_and_the_person_and_not_logged_as_shown():
    """The briefing, the compact action list and the person's line all name the second tier;
    with nothing in full they say what matched instead of "clean slate"; briefed_ids, which
    the exposure log reads, leaves the second tier out (REPORT §4y)."""
    s = _store_with([{"title": "retry the uploader with backoff",
                      "triggers": ["uploads to the bucket fail intermittently and the job gives up"],
                      "fix": "Wrap the call in a bounded retry. Log each attempt."},
                     {"title": "uploader logging format", "fix": "Use the structured logger."}])
    try:
        res = core.check(s, repo="r", task="the uploader job gives up when bucket uploads fail intermittently")
        text = core.render_check_for_agent(res)
        assert "### Also matched (1)" in text
        assert "- [r1] uploader logging format — Use the structured logger." in text
        assert "- [r1]" in core.render_actions_only(res)
        assert "1 more listed by title" in core.briefing_notice(res)
        assert core.briefed_ids(res) == ["r0"]
        loose = core.check(s, repo="r", task="change the uploader logging")
        assert loose["match_count"] == 0
        assert loose["also_matched"]
        assert "clean slate" not in core.render_check_for_agent(loose)
        assert "no encoded rule applies" not in core.render_actions_only(loose)
        assert core.briefing_notice(loose).startswith("okl · nothing matched closely enough to show in full")
    finally:
        s.close()


def test_two_rare_shared_words_clear_the_line_and_two_common_ones_do_not():
    """The line is three shared words, or two nearly as rare as a word in one record: two
    words that are in nearly every record are not enough on their own."""
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
    """Tiered unless set (§4y); OKL_DECISION wins over the config, an empty value falls
    through, and an unknown one is refused."""
    assert decision_setting(None, None) == "tiered"
    assert decision_setting(None, "calibrated") == "calibrated"
    assert decision_setting(None, "floor") == "floor"
    assert decision_setting("floor", "calibrated") == "floor"
    assert decision_setting("", "floor") == "floor"
    with pytest.raises(ValueError, match="decision"):
        decision_setting("strict", None)
    with pytest.raises(ValueError, match="decision"):
        core.check(Store("sqlite:///:memory:"), repo="r", task="x", decision="strict")


def test_check_follows_the_decision_flag_and_env(tmp_path):
    """`okl check` briefs by the tiered decision unless `--decision` or OKL_DECISION says
    otherwise; both reach core.check."""
    r = _okl(tmp_path, "record", "--type", "Rule", "--title", "uploader retries with backoff", "--scope", "org",
             "--trigger", "uploads fail intermittently and the job gives up", "--id", "u1")
    assert r.returncode == 0, r.stdout + r.stderr
    default = json.loads(_okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "json",
                              "--task", "the uploader job gives up on failed uploads").stdout)
    assert default["decision"] == "tiered" and [x["id"] for x in default["rules"]] == ["u1"]
    flag = json.loads(_okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "json",
                           "--decision", "floor", "--task", "the uploader job gives up on failed uploads").stdout)
    assert flag["decision"] == "floor"
    env = json.loads(_okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "json",
                          "--task", "the uploader job gives up on failed uploads",
                          env_extra={"OKL_DECISION": "floor"}).stdout)
    assert env["decision"] == "floor"


def test_recording_without_triggers_asks_for_them(tmp_path):
    """The default decision briefs a lesson by its title, symptom, aliases and triggers, so
    `okl record` without --trigger says so on stderr and names the command that adds them;
    stdout stays the bare id. A Vocabulary record, which only declares a tag, is not asked."""
    bare = _okl(tmp_path, "record", "--type", "Rule", "--title", "pin the linter", "--scope", "org", "--id", "p1")
    assert bare.returncode == 0 and bare.stdout.strip() == "p1", bare.stdout + bare.stderr
    assert "okl update p1 --trigger" in bare.stderr, bare.stderr
    given = _okl(tmp_path, "record", "--type", "Rule", "--title", "pin the formatter", "--scope", "org",
                 "--id", "p2", "--trigger", "CI fails on code nobody touched after a formatter release")
    assert given.returncode == 0 and "--trigger" not in given.stderr, given.stderr
    vocab = _okl(tmp_path, "record", "--type", "Vocabulary", "--scope", "org", "--title", "golang")
    assert vocab.returncode == 0 and "--trigger" not in vocab.stderr, vocab.stderr


def test_every_pack_lesson_carries_the_triggers_the_bench_measured():
    """The packs ship the triggers §4w measured (evals/bench/triggers.jsonl), lesson for lesson,
    so a pack edit and the bench cannot drift apart without this failing."""
    from collections import defaultdict
    measured: dict[str, list[str]] = defaultdict(list)
    for line in (ROOT / "evals" / "bench" / "triggers.jsonl").read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            measured[t["lesson"]].append(t["text"])
    shipped = {f"seed:{pack.stem}:{n['key']}": n["triggers"]
               for pack in sorted((ROOT / "seed").glob("*.json"))
               for n in json.loads(pack.read_text())["nodes"] if "triggers" in n}
    assert shipped == dict(measured)


def test_a_store_whose_bundled_packs_predate_triggers_is_told_to_refresh(tmp_path):
    """A store seeded before the packs carried triggers briefs their lessons less often under
    the calibrated default; the hook's line for the person says so and names `okl seed
    --refresh`, which clears it. A pack of the repo's own, not bundled, never prompts it."""
    def hook_line(task: str) -> str:
        out = _okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "hook", "--task", task)
        assert out.returncode == 0, out.stdout + out.stderr
        return json.loads(out.stdout).get("systemMessage", "")

    assert _okl(tmp_path, "seed", "react-defects").returncode == 0
    for n in json.loads((ROOT / "seed" / "react-defects.json").read_text())["nodes"]:
        assert _okl(tmp_path, "update", f"seed:react-defects:{n['key']}", "--trigger", "").returncode == 0
    task = "where should the SPA keep the access token so users stay logged in after a refresh"
    assert "okl seed --refresh" in hook_line(task)

    assert _okl(tmp_path, "seed", "--refresh").returncode == 0
    assert "okl seed --refresh" not in hook_line(task)

    own = tmp_path / "team-rules.json"
    own.write_text(json.dumps({"nodes": [{"key": "k1", "type": "Rule", "scope": "org", "repo": "r",
                                           "title": "token refresh goes through the auth client",
                                           "found_by": "a review"}]}))
    assert _okl(tmp_path, "seed", str(own)).returncode == 0
    assert "okl seed --refresh" not in hook_line(task)


def test_accented_words_count_toward_the_line():
    """The decision splits words as the task tokenizer does, Unicode letters included: an
    ASCII-only pattern cut "café" to "caf", so an accented task word never counted (review on
    #292)."""
    assert decide.words("Le café résumé, naïve parser") == {"le", "café", "résumé", "naïve", "parser"}
    s = _store_with([{"title": "résumé parser for the café menu"}])
    try:
        node = s.all_nodes()[0]
        rarity = decide.Rarity(s.all_nodes())
        sc, shared = decide.score(core.briefing_terms("fix the résumé parser on the café menu"), node, rarity)
        assert set(shared) == {"résumé", "parser", "café", "menu"} and sc >= decide.CALIBRATED_LINE
    finally:
        s.close()


def test_a_remote_check_says_which_decision_answered(monkeypatch):
    """A service that predates `decision` answers by the floor. The briefing is not refused,
    since every client asks for a decision and refusing would block every prompt until the
    service is upgraded; the result says which decision answered, and why (review on #292)."""
    from okl.client import Client
    c = Client(config={"repo": "r", "service_url": "http://service.invalid"})
    monkeypatch.setattr("okl.client.drift.annotate_briefing", lambda *a, **k: None)
    monkeypatch.setattr(c, "_post", lambda path, body: {"repo": "r", "task": body["task"], "rules": [], "match_count": 0})
    old = c.check("a task")
    assert old["decision"] == "floor" and "upgrade the service" in old["decision_unavailable"]
    monkeypatch.setattr(c, "_post", lambda path, body: {"repo": "r", "task": body["task"], "rules": [],
                                                         "match_count": 0, "decision": body["decision"]})
    new = c.check("a task")
    assert new["decision"] == "tiered" and "decision_unavailable" not in new


def test_okl_triggers_lists_own_advice_lessons_without_triggers_and_the_briefing_names_them(tmp_path):
    """`okl triggers` lists the store's own advice lessons with no triggers (a pack's lessons,
    Vocabulary and lessons with triggers left out), and the hook's line for the person names
    how many once there are at least three (REPORT §4x)."""
    def hook_line() -> str:
        out = _okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "hook",
                   "--task", "rotate the signing keys for the token service")
        assert out.returncode == 0, out.stdout + out.stderr
        return json.loads(out.stdout).get("systemMessage", "")

    for i in range(2):
        assert _okl(tmp_path, "record", "--type", "Rule", "--scope", "org", "--id", f"own{i}",
                    "--title", f"own lesson {i}").returncode == 0
    assert _okl(tmp_path, "record", "--type", "Rule", "--scope", "org", "--id", "with", "--title", "has triggers",
                "--trigger", "rotate the signing keys without downtime").returncode == 0
    assert _okl(tmp_path, "record", "--type", "Vocabulary", "--scope", "org", "--title", "golang").returncode == 0
    assert _okl(tmp_path, "seed", "react-defects").returncode == 0
    listed = json.loads(_okl(tmp_path, "triggers", "--format", "json").stdout)
    assert sorted(x["id"] for x in listed) == ["own0", "own1"]
    # One lesson by id, for /triggers <id> (review on #298); one with triggers lists nothing.
    assert [x["id"] for x in json.loads(_okl(tmp_path, "triggers", "own1", "--format", "json").stdout)] == ["own1"]
    assert json.loads(_okl(tmp_path, "triggers", "with", "--format", "json").stdout) == []
    # In text, it answers for the lesson asked about, while others still lack triggers.
    text = _okl(tmp_path, "triggers", "with").stdout
    assert "with needs no triggers" in text
    assert "every advice lesson" not in text
    assert "have no triggers" not in hook_line()            # two: below the notice's threshold
    assert _okl(tmp_path, "record", "--type", "Defect", "--scope", "org", "--id", "own2",
                "--title", "own lesson 2").returncode == 0
    assert "3 of this store's own lessons have no triggers" in hook_line()
    assert _okl(tmp_path, "update", "own2", "--trigger", "a third lesson finally gets its words").returncode == 0
    assert "have no triggers" not in hook_line()


def test_a_teams_own_pack_counts_and_a_bundled_pack_does_not(tmp_path):
    """Only the bundled packs ship triggers, so only their lessons are left out of `okl
    triggers`: a team's own pack, seeded from its own file, is the team's to give triggers
    (review on #298)."""
    own = tmp_path / "team-rules.json"
    own.write_text(json.dumps({"nodes": [{"key": "k1", "type": "Rule", "scope": "org", "repo": "r",
                                           "title": "token refresh goes through the auth client",
                                           "found_by": "a review"}]}))
    assert _okl(tmp_path, "seed", str(own)).returncode == 0
    assert _okl(tmp_path, "seed", "react-defects").returncode == 0
    for n in json.loads((ROOT / "seed" / "react-defects.json").read_text())["nodes"]:
        assert _okl(tmp_path, "update", f"seed:react-defects:{n['key']}", "--trigger", "").returncode == 0
    listed = [x["id"] for x in json.loads(_okl(tmp_path, "triggers", "--format", "json").stdout)]
    assert listed == ["seed:team-rules:k1"]
