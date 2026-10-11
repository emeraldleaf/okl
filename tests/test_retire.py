"""Retiring a lesson is a verb, with a reason (okl review R2).

Before: "retracted" was the only way out. Retracting through the CLI meant re-recording the
lesson, which wiped its body, fix, tags and proof; and `check` never read SUPERSEDES, so a
replaced lesson kept being briefed beside its replacement. One reproduced briefing told
the agent to AVOID a superseded Decision as false while listing the live replacement under
"made on purpose".

Now `okl retire <id> --reason "..."` has three outcomes:
- wrong (the default): status retracted, briefed as AVOID, every field kept;
- `--by <new>`: status superseded, a `<new> SUPERSEDES <id>` edge, left out before the
  briefing's cut with a one-line pointer to the replacement;
- `--obsolete`: status obsolete, no longer briefed.
A resolved defect is not retired and keeps briefing against its return. Each retirement
keeps its reason, in a log the lesson's own row cannot overwrite.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from okl import core
from okl.cli import main
from okl.client import Client
from okl.store import Store

COMMIT = "b" * 40


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repo with a local store."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    return tmp_path


def _lessons(c: Client) -> None:
    c.record(id="refund-old", type="Rule", title="refunds post to the ledger after the charge",
             scope="repo", symptom="a refund endpoint", fix="post the refund after the charge",
             body="refund ledger ordering", tags="security", files="src/refunds.py")
    c.record(id="refund-new", type="Rule", title="refunds post to the ledger before the charge",
             scope="repo", symptom="a refund endpoint", fix="post the refund first",
             body="refund ledger ordering, revised")


def _briefing(task: str = "add a refund endpoint that posts to the ledger",
              limit: int | None = None) -> str:
    argv = ["check", "--task", task] + (["--limit", str(limit)] if limit else [])
    assert main(argv) == 0
    return argv  # the caller reads capsys


def test_retiring_a_wrong_lesson_keeps_it_and_briefs_it_as_avoid(repo, capsys):
    """Retracting used to mean re-recording, which wiped the lesson's content and proof."""
    # ARRANGE
    c = Client()
    _lessons(c)
    c.verify("refund-old", "`pytest -q` exit 0", commit=COMMIT)
    before = c.get("refund-old")
    capsys.readouterr()

    # ACT
    code = main(["retire", "refund-old", "--reason", "the ledger posts refunds first"])
    out = capsys.readouterr().out

    # ASSERT (1) — retracted, everything else kept, and the reason on record
    assert code == 0 and "retired refund-old" in out, out
    after = Client().get("refund-old")
    assert after["status"] == "retracted"
    for field in ("title", "fix", "tags", "files", "body", "verified_by", "created_at"):
        assert after[field] == before[field], field
    assert [(r["kind"], r["reason"]) for r in after["retirements"]] == [
        ("wrong", "the ledger posts refunds first")]

    # ASSERT (2) — briefed as a prohibition, with its id
    _briefing()
    text = capsys.readouterr().out
    assert "AVOID: refunds post to the ledger after the charge" in text, text
    assert "[refund-old]" in text


def test_a_superseded_lesson_leaves_the_briefing_and_points_to_its_replacement(repo, capsys):
    """check never read SUPERSEDES, so a replaced lesson was briefed beside its replacement,
    one of them under 'made on purpose; do not silently reverse'."""
    # ARRANGE
    _lessons(Client())

    # ACT
    assert main(["retire", "refund-old", "--by", "refund-new",
                 "--reason", "the order was reversed"]) == 0
    capsys.readouterr()
    _briefing()
    text = capsys.readouterr().out

    # ASSERT (1) — the old lesson is not briefed as guidance or as AVOID
    assert "- **FIX: refunds post to the ledger after the charge" not in text
    assert "AVOID: refunds post to the ledger after the charge" not in text
    # ASSERT (2) — one line points from it to its replacement, by id
    assert "[refund-old]" in text and "[refund-new]" in text, text
    assert "replaced by" in text.lower(), text
    # ASSERT (3) — the edge and the status say so too
    after = Client().get("refund-old")
    assert after["status"] == "superseded"
    assert after["retirements"][0]["by"] == "refund-new"


def test_a_superseded_lesson_drops_out_before_the_cut(repo, capsys):
    """It must not take one of the briefing's slots from a live lesson."""
    # ARRANGE — the old lesson outranks the new one for this task
    _lessons(Client())
    assert main(["retire", "refund-old", "--by", "refund-new", "--reason", "reversed"]) == 0
    capsys.readouterr()

    # ACT — a briefing with room for one lesson
    assert main(["check", "--task", "refunds post to the ledger after the charge",
                 "--limit", "1", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)

    # ASSERT — the one slot goes to a live lesson
    shown = [r["id"] for k in ("rules", "relevant_defects", "decisions", "context",
                               "live_retractions") for r in result.get(k, [])]
    assert shown == ["refund-new"], shown


def test_an_obsolete_lesson_is_no_longer_briefed(repo, capsys):
    """A lesson about code that no longer exists is neither guidance nor a warning."""
    # ARRANGE
    _lessons(Client())

    # ACT
    assert main(["retire", "refund-old", "--obsolete", "--reason", "refunds were removed"]) == 0
    capsys.readouterr()
    _briefing()
    text = capsys.readouterr().out

    # ASSERT
    assert "refunds post to the ledger after the charge" not in text, text
    assert Client().get("refund-old")["status"] == "obsolete"


def test_a_resolved_defect_keeps_briefing_against_its_return(repo, capsys):
    """Resolved is not retired: the fix happened, and the briefing still warns against
    the defect coming back."""
    # ARRANGE
    Client().record(id="d1", type="Defect", title="refund amount trusted from the body",
                    scope="repo", symptom="a refund endpoint reads amount", fix="look it up",
                    status="resolved")

    # ACT
    _briefing("add a refund endpoint that reads the amount")

    # ASSERT
    assert "FIX: refund amount trusted from the body" in capsys.readouterr().out


@pytest.mark.parametrize("argv, says", [
    (["retire", "refund-old", "--reason", "  "], "reason"),
    (["retire", "nope", "--reason", "x"], "no lesson"),
    (["retire", "refund-old", "--by", "nope", "--reason", "x"], "no lesson"),
    (["retire", "refund-old", "--by", "refund-old", "--reason", "x"], "itself"),
])
def test_retire_refuses_what_it_cannot_do_and_writes_nothing(repo, capsys, argv, says):
    """Exit 2 is "could not run"; a refused retirement changes nothing."""
    # ARRANGE
    _lessons(Client())
    before = Client().get("refund-old")
    capsys.readouterr()

    # ACT
    code = main(argv)
    out, err = capsys.readouterr()

    # ASSERT
    assert code == 2 and out == "", (code, out)
    assert says in err.lower(), err
    assert Client().get("refund-old") == before


@pytest.mark.parametrize("argv, says", [
    (["retire", "refund-old"], "--reason"),
    (["retire", "refund-old", "--by", "refund-new", "--obsolete", "--reason", "x"],
     "not allowed with"),
])
def test_the_cli_refuses_a_retirement_it_cannot_parse(repo, capsys, argv, says):
    """A missing reason, and replaced-and-obsolete at once, never reach the store."""
    _lessons(Client())
    before = Client().get("refund-old")
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(argv)
    # argparse's own refusal, naming the problem; not "invalid choice: 'retire'"
    assert exc.value.code == 2 and says in capsys.readouterr().err
    assert Client().get("refund-old") == before


def test_core_refuses_replaced_and_obsolete_at_once():
    """The API and a service enforce it too, not only argparse."""
    s = Store("sqlite:///:memory:")
    core.record(s, id="a", type="Rule", title="a", scope="org")
    core.record(s, id="b", type="Rule", title="b", scope="org")
    with pytest.raises(ValueError, match="not both"):
        core.retire(s, "a", "x", by="b", obsolete=True)
    assert s.get_node("a").status is None and s.retirements("a") == []


def test_reseeding_keeps_a_retirement(repo):
    """okl seed rewrites a pack's lessons from the pack; a status set here must survive."""
    from okl.seed import seed_from_file

    # ARRANGE — a seeded lesson, retired here
    pack = repo / "site.json"
    pack.write_text(json.dumps({"nodes": [{"key": "grid", "type": "Rule", "scope": "org",
                                           "repo": "r", "title": "Grid minimums fit"}]}))
    seed_from_file(Client(), str(pack))
    assert main(["retire", "seed:site:grid", "--obsolete", "--reason", "no grid any more"]) == 0

    # ACT
    seed_from_file(Client(), str(pack))

    # ASSERT
    assert Client().get("seed:site:grid")["status"] == "obsolete"


def test_drift_leaves_retired_lessons_alone(repo):
    """A withdrawn lesson is not a rule to keep proven: drift and the committed snapshot
    used to keep asking for it to be re-verified."""
    from okl import drift

    # ARRANGE — a git repo with a governed file, and a lesson that governs it, retired
    subprocess.run(["git", "init", "-q", "."], check=True)
    (repo / "src").mkdir()
    (repo / "src" / "refunds.py").write_text("x = 1\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"],
                   check=True)
    _lessons(Client())
    assert main(["retire", "refund-old", "--reason", "wrong"]) == 0
    nodes = Client().all_nodes()

    # ACT
    hits, checked = drift.scan_drift(nodes, "r", str(repo))
    snap = drift.snapshot(nodes, "r")

    # ASSERT
    assert "refund-old" not in {h.node_id for h in hits}
    assert "refund-old" not in {r["id"] for r in snap["rules"]}


def test_show_says_how_and_why_a_lesson_was_retired(repo, capsys):
    """An agent shown an id needs to see that the lesson was withdrawn, and why."""
    # ARRANGE
    _lessons(Client())
    assert main(["retire", "refund-old", "--by", "refund-new", "--reason", "reversed"]) == 0
    capsys.readouterr()

    # ACT
    assert main(["show", "refund-old"]) == 0
    text = capsys.readouterr().out

    # ASSERT
    assert "superseded" in text and "refund-new" in text and "reversed" in text, text


def test_a_retirement_survives_an_older_okl_rewriting_the_lesson(repo):
    """The reason lives in its own log, not in a column on the lesson's row: an okl from
    before R2 rewrites whole rows on SQLite, and would silently blank a column it did not
    know about (the risk the review named for any new node column)."""
    # ARRANGE
    _lessons(Client())
    assert main(["retire", "refund-old", "--reason", "wrong"]) == 0
    store = Store(f"sqlite:///{repo / '.okl' / 'okl.db'}")

    # ACT — rewrite the row the way any older writer does: the node as it reads it
    n = store.get_node("refund-old")
    store.add_node(n)

    # ASSERT
    assert [r.reason for r in store.retirements("refund-old")] == ["wrong"]


def test_mcp_and_a_service_can_retire(remote):
    """Agents on MCP and repos on a service get the same verb, through the real client."""
    import asyncio
    pytest.importorskip("mcp")
    from okl.mcp_server import _build

    # ARRANGE
    core.record(remote.store, id="a", type="Rule", title="old", scope="org")
    core.record(remote.store, id="b", type="Rule", title="new", scope="org")

    def text(res):
        if isinstance(res, tuple):
            res = res[0]
        c = getattr(res, "content", res)
        if isinstance(c, list | tuple):
            c = c[0]
        return getattr(c, "text", str(c))

    # ACT
    out = text(asyncio.run(_build().call_tool("okl_retire", {
        "id": "a", "reason": "replaced", "by": "b"})))

    # ASSERT
    assert out.startswith("retired a"), out
    assert remote.store.get_node("a").status == "superseded"
    assert [(r.kind, r.by) for r in remote.store.retirements("a")] == [("superseded", "b")]


# ---- found by the two reviews of R2 (2026-10-10) ----------------------------------------

def _store_with(*records) -> Store:
    s = Store("sqlite:///:memory:")
    for r in records:
        core.record(s, **r)
    return s


def test_reseeding_keeps_a_retirement_when_the_pack_sets_a_status(repo):
    """Eight bundled lessons say "live": the guard only covered a pack with no status."""
    from okl.seed import seed_from_file

    # ARRANGE
    pack = repo / "site.json"
    pack.write_text(json.dumps({"nodes": [{"key": "grid", "type": "Rule", "scope": "org",
                                           "repo": "r", "title": "Grid", "status": "live"}]}))
    seed_from_file(Client(), str(pack))
    assert main(["retire", "seed:site:grid", "--obsolete", "--reason", "gone"]) == 0

    # ACT
    seed_from_file(Client(), str(pack))

    # ASSERT
    assert Client().get("seed:site:grid")["status"] == "obsolete"


def test_a_replacement_must_be_live_and_visible_where_the_lesson_was():
    """A retired replacement (and so a cycle) left neither lesson briefed; a narrower one
    hid an org lesson from every other repo and named a private title in their briefings."""
    s = _store_with(dict(id="a", type="Rule", title="a", scope="org"),
                    dict(id="b", type="Rule", title="b", scope="org"),
                    dict(id="x", type="Rule", title="x", scope="repo:x"))
    core.retire(s, "a", "replaced", by="b")

    with pytest.raises(ValueError, match="itself retired"):     # the cycle: b by a
        core.retire(s, "b", "back", by="a")
    with pytest.raises(ValueError, match="narrower"):
        core.retire(s, "b", "private", by="x")
    assert s.get_node("b").status is None


def test_the_pointer_follows_the_latest_replacement_through_a_chain():
    """Edges have no order: after a second --by the pointer stayed on the first."""
    s = _store_with(*(dict(id=i, type="Rule", title=f"refund ledger {i}", scope="org",
                           fix="f") for i in ("a", "b", "c", "d")))
    core.retire(s, "a", "first", by="b")
    core.retire(s, "a", "second", by="c")       # the latest replacement wins
    core.retire(s, "c", "chain", by="d")        # and a chain is followed to a live one

    res = core.check(s, "r", "refund ledger a")

    assert [(r["id"], r["by"]) for r in res["replaced"]] == [("a", "d"), ("c", "d")]


def test_a_superseded_lesson_with_no_visible_replacement_stays_briefed():
    """Dropping it would leave the repo with nothing: older data, or a replacement this
    repo cannot see, keeps the old lesson in the briefing."""
    s = _store_with(dict(id="a", type="Rule", title="refund ledger order", scope="org", fix="f"),
                    dict(id="x", type="Rule", title="x", scope="repo:x"))
    n = s.get_node("a")
    n.status = "superseded"
    s.add_node(n)
    s.add_edge(core.Edge(src="x", rel="SUPERSEDES", dst="a"))

    res = core.check(s, "y", "refund ledger order")

    assert [r["id"] for r in res["rules"]] == ["a"] and res["replaced"] == []


def test_retired_lessons_do_not_use_up_the_search_window():
    """Three obsolete matches above a live one left a one-slot briefing empty, saying
    nothing matched."""
    s = _store_with(*(dict(id=f"gone{i}", type="Rule", title="refund ledger refund ledger",
                           scope="org", fix="f") for i in range(3)),
                    dict(id="live", type="Rule", title="refund ledger", scope="org", fix="f"))
    for i in range(3):
        core.retire(s, f"gone{i}", "gone", obsolete=True)

    res = core.check(s, "r", "refund ledger", limit=1)

    assert [r["id"] for r in res["rules"]] == ["live"]


def test_update_and_record_cannot_set_or_clear_a_retirement():
    """`okl retire` keeps the reason and the replacement; update and record went around it."""
    s = _store_with(dict(id="a", type="Rule", title="a", scope="org"),
                    dict(id="b", type="Rule", title="b", scope="org"))
    for status in ("superseded", "obsolete", "retracted"):
        with pytest.raises(ValueError, match="okl retire"):
            core.update(s, "a", status=status)
    with pytest.raises(ValueError, match="okl retire"):
        core.record(s, type="Rule", title="c", scope="org", status="obsolete")
    core.retire(s, "a", "replaced", by="b")
    with pytest.raises(ValueError, match="okl retire"):
        core.update(s, "a", status="live")
    with pytest.raises(ValueError, match="okl retire"):
        core.update(s, "a", status="")
    core.record(s, id="a", type="Rule", title="a again", scope="org", replace=True)
    assert s.get_node("a").status == "superseded"


def test_a_retired_lesson_is_not_marked_stale_and_retiring_refreshes_the_snapshot(
        repo, capsys, monkeypatch):
    """Drift skips a retired lesson; the briefing's STALE mark and CI's snapshot must agree."""
    from okl import drift

    # ASSERT (1) — no drift verdict for a retired record
    assert drift._record_drift({"files": "a.py", "scope": "org", "status": "retracted"},
                               "repo:r", str(repo)) is None
    # ASSERT (2) — retiring a lesson that governs files refreshes the committed snapshot
    calls = []
    monkeypatch.setattr("okl.cli.lessons._refresh_snapshot",
                        lambda node, why="": calls.append((node["id"], why)))
    _lessons(Client())
    assert main(["retire", "refund-new", "--reason", "x"]) == 0      # governs no files
    assert main(["retire", "refund-old", "--reason", "x"]) == 0      # governs src/refunds.py
    assert calls == [("refund-old", "its retirement")]


def test_exposure_does_not_count_retired_lessons():
    """The pointer list counted as shown, and an obsolete lesson was offered for review."""
    s = _store_with(dict(id="a", type="Rule", title="refund ledger", scope="org", fix="f"),
                    dict(id="b", type="Rule", title="refund ledger new", scope="org", fix="f"),
                    dict(id="c", type="Rule", title="other", scope="org"))
    core.retire(s, "a", "replaced", by="b")
    core.retire(s, "c", "gone", obsolete=True)

    res = core.check(s, "r", "refund ledger")
    assert "a" not in core.briefed_ids(res)
    s.log_briefing("r", core.briefed_ids(res))
    report = core.exposure_report(s, "r")
    assert report["reachable"] == 1
    assert "c" not in [r["id"] for r in report["never_shown"]]


def test_a_briefing_with_only_a_pointer_does_not_say_nothing_matched():
    """A pointer is a match: "nothing matched" above it contradicted the line below."""
    s = _store_with(dict(id="a", type="Rule", title="refund ledger", scope="org", fix="f"),
                    dict(id="b", type="Rule", title="new", scope="org", fix="g"))
    core.retire(s, "a", "replaced", by="b")
    res = core.check(s, "r", "refund ledger")

    assert "No encoded rule matched" not in core.render_check_for_agent(res)
    assert "no encoded rule applies" not in core.render_actions_only(res)
    assert "[a] was replaced by new [b]" in core.render_actions_only(res)


def test_dedup_recommends_retire(repo, capsys):
    """okl dedup told people to link SUPERSEDES by hand, which check did not read."""
    c = Client()
    c.record(type="Rule", title="refunds post to the ledger before the charge", scope="repo",
             body="refund ledger ordering rule")
    c.record(type="Rule", title="refunds post to the ledger before the charge", scope="repo",
             body="refund ledger ordering rule")
    capsys.readouterr()
    main(["dedup"])
    assert "okl retire" in capsys.readouterr().out


def test_a_new_record_cannot_arrive_already_retired_even_on_the_import_path():
    """keep_verification (okl seed's path, and a service's /record) skipped the guard, so a
    new stable id could be created superseded or obsolete with no reason (CodeRabbit, #163)."""
    s = _store_with(dict(id="a", type="Rule", title="a", scope="org"))
    with pytest.raises(ValueError, match="okl retire"):
        core.record(s, id="new", type="Rule", title="n", scope="org", status="obsolete",
                    keep_verification=True)
    assert s.get_node("new") is None
    # a re-import of a lesson retired here still passes, and keeps its retirement
    core.retire(s, "a", "gone", obsolete=True)
    core.record(s, id="a", type="Rule", title="a", scope="org", status="obsolete",
                keep_verification=True)
    assert s.get_node("a").status == "obsolete"


def test_retire_logs_the_reason_before_it_changes_the_status():
    """The writes are not one transaction; a failure part-way must never leave a retired
    lesson with no reason, which only okl retire could then touch (CodeRabbit, #163)."""
    s = _store_with(dict(id="a", type="Rule", title="a", scope="org"))

    def fail(node):
        raise RuntimeError("disk full")
    s.add_node = fail

    with pytest.raises(RuntimeError):
        core.retire(s, "a", "wrong")
    del s.add_node
    assert s.get_node("a").status is None
    assert [r.reason for r in s.retirements("a")] == ["wrong"]
