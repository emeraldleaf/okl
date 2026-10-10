"""Lessons are addressable and safely editable (okl review R1).

Incident: re-recording a lesson with its `--id`, which the Stop hook, `/record` and the
encoding-loop skill all told agents to do to refine one, replaced the whole row. Its
verification, its governed files and its creation date were wiped, and the lesson quietly
left drift. The briefing printed no ids, so an agent could not address a lesson it had
just been shown without searching for it first.

Now: every briefed lesson carries its `[id]`; `okl update <id>` merges the fields given
and keeps the proof unless the governed files change; `okl record --id <existing>`
refuses without `--replace`; `okl show <id>` prints one lesson; and the first creation
date survives every rewrite.
"""
from __future__ import annotations

import json

import pytest

from okl.cli import main
from okl.client import Client

COMMIT = "a" * 40


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repo with a local store, nothing pointing anywhere else."""
    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    return tmp_path


def _proven_lesson(lesson_id: str = "price-server-side") -> dict:
    """Record a lesson that governs a file and stamp it from an observed check."""
    c = Client()
    c.record(id=lesson_id, type="Rule", title="price comes from the catalogue",
             scope="repo", symptom="a request body carries a price", fix="look it up",
             files="src/orders.py", tags="security")
    c.verify(lesson_id, "`pytest -q tests/test_orders.py` exit 0", commit=COMMIT)
    return c.get(lesson_id)


def test_recording_over_an_existing_id_refuses_and_leaves_the_lesson_alone(repo, capsys):
    """Recording an existing id used to replace the row and wipe its proof; now it refuses."""
    # ARRANGE — a proven lesson
    before = _proven_lesson()
    capsys.readouterr()

    # ACT — record it again with the same id, as every surface used to teach
    code = main(["record", "--id", "price-server-side", "--type", "Rule", "--scope", "repo",
                 "--title", "a reworded title", "--fix", "a new fix"])
    out, err = capsys.readouterr()

    # ASSERT (1) — refused, with the command that does what was meant
    assert code == 2 and out == "", (code, out)
    assert "already exists" in err and "okl update price-server-side" in err, err
    assert "--replace" in err, err
    # ASSERT (2) — nothing about the stored lesson changed: wording, proof or dates
    assert Client().get("price-server-side") == before


def test_update_merges_the_fields_given_and_keeps_proof_and_creation_date(repo, capsys):
    """Refining a lesson's wording keeps the check that proved it and when it was first made."""
    # ARRANGE
    before = _proven_lesson()
    capsys.readouterr()

    # ACT — refine the wording only
    code = main(["update", "price-server-side", "--fix", "read unitPrice from the catalogue",
                 "--symptom", "an order request carries unitPrice"])
    out, err = capsys.readouterr()

    # ASSERT (1) — updated, and it says the proof was kept
    assert code == 0, err
    assert "updated price-server-side" in out and "proof kept" in out, out
    after = Client().get("price-server-side")
    # ASSERT (2) — the given fields changed, the rest did not
    assert after["fix"] == "read unitPrice from the catalogue"
    assert after["symptom"] == "an order request carries unitPrice"
    assert after["title"] == before["title"] and after["tags"] == "security"
    # ASSERT (3) — the proof and the first creation date survive a change of wording
    for field in ("verified_at", "verified_by", "verified_commit", "files", "created_at"):
        assert after[field] == before[field], field


def test_update_that_changes_the_governed_files_clears_the_proof(repo, capsys):
    """A stamp proves the files it was checked against, so new files mean no proof yet."""
    # ARRANGE
    _proven_lesson()
    capsys.readouterr()

    # ACT — the lesson now governs different code
    code = main(["update", "price-server-side", "--files", "src/checkout.py"])
    out, _ = capsys.readouterr()

    # ASSERT — a check of other files proves nothing about these, so the stamp goes; the
    # stored check stays, so okl reverify can re-run it (see the reverify test below)
    assert code == 0
    after = Client().get("price-server-side")
    assert after["files"] == "src/checkout.py"
    assert after["verified_at"] is None and after["verified_commit"] is None
    assert "proof cleared" in out and "okl reverify" in out, out


def test_update_with_an_empty_value_clears_that_field(repo, capsys):
    """An empty value is how a field is unset, since leaving a flag off leaves it alone."""
    # ARRANGE
    Client().record(id="l1", type="Rule", title="t", scope="repo", applies_to="python")
    capsys.readouterr()

    # ACT
    code = main(["update", "l1", "--applies-to", ""])

    # ASSERT — an empty value unsets an optional field
    assert code == 0
    assert Client().get("l1")["applies_to"] is None


@pytest.mark.parametrize("argv, says", [
    (["update", "no-such-lesson", "--fix", "x"], "no lesson"),
    (["update", "l1"], "nothing to change"),
    (["update", "l1", "--title", ""], "title"),
    (["update", "l1", "--tags", "not-a-real-tag"], "vocabulary"),
])
def test_update_refuses_what_it_cannot_do_and_writes_nothing(repo, capsys, argv, says):
    """Exit 2 means could not run; a refused update must not half-apply."""
    # ARRANGE
    Client().record(id="l1", type="Rule", title="t", scope="repo", fix="f")
    before = Client().get("l1")
    capsys.readouterr()

    # ACT
    code = main(argv)
    out, err = capsys.readouterr()

    # ASSERT — exit 2 is "could not run", with the reason, and the lesson is untouched
    assert code == 2 and out == "", (code, out)
    assert says in err.lower(), err
    assert Client().get("l1") == before


def test_replace_overwrites_the_lesson_but_keeps_its_first_creation_date(repo, capsys):
    """--replace is the deliberate overwrite; even it keeps when the lesson was first made."""
    # ARRANGE
    before = _proven_lesson()
    capsys.readouterr()

    # ACT — a deliberate overwrite
    code = main(["record", "--id", "price-server-side", "--replace", "--type", "Decision",
                 "--scope", "repo", "--title", "prices are server-side by decision"])

    # ASSERT — new content, no inherited proof, the same first creation date
    assert code == 0
    after = Client().get("price-server-side")
    assert after["type"] == "Decision" and after["fix"] is None
    assert after["verified_at"] is None and after["files"] is None
    assert after["created_at"] == before["created_at"]


def test_show_prints_one_lesson_with_its_id_and_proof(repo, capsys):
    """An agent shown an id needs a way to read the whole lesson behind it."""
    # ARRANGE
    _proven_lesson()
    capsys.readouterr()

    # ACT
    assert main(["show", "price-server-side"]) == 0
    text = capsys.readouterr().out
    assert main(["show", "price-server-side", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)

    # ASSERT — the human form names the id, the fix and the evidence; json is the record
    assert "[price-server-side]" in text and "look it up" in text
    assert "pytest -q tests/test_orders.py" in text
    assert data["id"] == "price-server-side" and data["verified_commit"] == COMMIT

    # ASSERT — a missing id could not run
    assert main(["show", "no-such-lesson"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and "no lesson" in err.lower()


def test_every_briefed_lesson_carries_its_id(repo, capsys):
    """The briefing printed titles only, so an agent had to search before it could update
    or retire a lesson it had just been shown."""
    # ARRANGE — one lesson routed into an action, one that lands in a section
    c = Client()
    c.record(id="refund-idempotency", type="Defect", title="refund retried twice",
             scope="repo", symptom="a refund endpoint without an idempotency key",
             fix="require an Idempotency-Key header")
    c.record(id="refund-ledger", type="Decision", title="refunds post to the ledger first",
             scope="repo", body="refund ledger decision")
    capsys.readouterr()

    # ACT — the full briefing and the compact one
    assert main(["check", "--task", "add a refund endpoint to the ledger"]) == 0
    full = capsys.readouterr().out
    assert main(["check", "--task", "add a refund endpoint to the ledger", "--compact"]) == 0
    compact = capsys.readouterr().out

    # ASSERT — each lesson's line names its id, in both forms
    assert "[refund-idempotency]" in full and "[refund-ledger]" in full, full
    assert "[refund-idempotency]" in compact, compact


def test_the_mcp_tools_refuse_an_existing_id_and_update_and_get_by_id(repo):
    """Agents on MCP get the same verbs and the same refusal as the CLI."""
    import asyncio
    pytest.importorskip("mcp")
    from okl.mcp_server import _build

    # ARRANGE
    _proven_lesson()

    def text(res):
        if isinstance(res, tuple):   # mcp 1.x: (content blocks, structured result)
            res = res[0]
        c = getattr(res, "content", res)
        if isinstance(c, list | tuple):
            c = c[0]
        return getattr(c, "text", str(c))

    async def exercise():
        mcp = _build()
        names = {t.name for t in await mcp.list_tools()}
        # ASSERT (1) — the agent-facing surface has the new verbs
        assert {"okl_update", "okl_get"} <= names, names
        # ASSERT (2) — recording over an existing id refuses and names the tool to use
        refused = text(await mcp.call_tool("okl_record", {
            "id": "price-server-side", "type": "Rule", "title": "x", "scope": "repo"}))
        assert refused.startswith("NOT RECORDED") and "okl_update" in refused, refused
        # ASSERT (3) — update merges and keeps the proof
        done = text(await mcp.call_tool("okl_update", {
            "id": "price-server-side", "fix": "read it from the catalogue"}))
        assert "proof kept" in done, done
        # ASSERT (4) — get returns the lesson with its proof
        got = json.loads(text(await mcp.call_tool("okl_get", {"id": "price-server-side"})))
        assert got["fix"] == "read it from the catalogue" and got["verified_commit"] == COMMIT

    asyncio.run(exercise())


def test_the_service_refuses_an_existing_id_and_serves_update_and_get():
    """A repo connected to a service must behave as a local one does."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from okl import core
    from okl.service import create_app
    from okl.store import Store

    # ARRANGE — a proven lesson in the store a service serves
    s = Store("sqlite:///:memory:")
    core.record(s, id="l1", type="Rule", title="t", scope="org", files="a.py", fix="f")
    core.verify(s, "l1", "`pytest -q` exit 0", commit=COMMIT)
    api = TestClient(create_app(store=s))

    # ASSERT (1) — re-recording the id is the caller's error, with the message
    r = api.post("/record", json={"id": "l1", "type": "Rule", "title": "x", "scope": "org"})
    assert r.status_code == 400 and "already exists" in r.json()["detail"]
    # ASSERT (2) — update merges and keeps the proof
    r = api.post("/update", json={"id": "l1", "fields": {"fix": "g"}})
    assert r.status_code == 200 and r.json()["fix"] == "g"
    assert r.json()["verified_commit"] == COMMIT
    # ASSERT (3) — get returns it, and an unknown id is an explicit null: a 404 is kept for
    # a service too old to have the route, which must not read as "no such lesson"
    assert api.get("/node/l1").json()["node"]["title"] == "t"
    r = api.get("/node/nope")
    assert r.status_code == 200 and r.json() == {"node": None}
    # ASSERT (4) — --replace reaches the service
    r = api.post("/record", json={"id": "l1", "type": "Rule", "title": "x", "scope": "org",
                                  "replace": True})
    assert r.status_code == 200


# ---- found by the two reviews of R1 (2026-10-10) ----------------------------------------

@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A repo connected to an okl service served in-process: the Client's real remote code
    (urllib, its error mapping) talks to the real app, with no socket. Both reviews found
    remote paths that only ever had their service posted to directly, never via Client."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import io
    from types import SimpleNamespace
    from urllib.error import HTTPError
    from urllib.parse import urlsplit

    from fastapi.testclient import TestClient

    from okl.service import create_app
    from okl.store import Store

    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(
        json.dumps({"repo": "r", "service_url": "http://okl.test"}))
    store = Store("sqlite:///:memory:")
    app = create_app(store=store)
    api = TestClient(app)

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def urlopen(req, timeout=None):
        u = urlsplit(req.full_url)
        r = api.request(req.get_method(), u.path + (f"?{u.query}" if u.query else ""),
                        content=req.data, headers=dict(req.header_items()))
        if r.status_code >= 400:
            raise HTTPError(req.full_url, r.status_code, r.reason_phrase, None,
                            io.BytesIO(r.content))
        return Reply(r.content)

    monkeypatch.setattr("okl.client._req.urlopen", urlopen)
    return SimpleNamespace(store=store, app=app, api=api)


def _mcp_text(res):
    if isinstance(res, tuple):   # mcp 1.x: (content blocks, structured result)
        res = res[0]
    c = getattr(res, "content", res)
    if isinstance(c, list | tuple):
        c = c[0]
    return getattr(c, "text", str(c))


def test_mcp_record_works_over_a_service_and_points_only_to_update(remote):
    """okl_record sent replace=null, which the service refused: every record over MCP to a
    service failed unless the agent asked for the destructive overwrite."""
    import asyncio
    pytest.importorskip("mcp")
    from okl.mcp_server import _build

    async def exercise():
        mcp = _build()
        # ASSERT (1) — a new lesson records, with an id and without one
        assert _mcp_text(await mcp.call_tool("okl_record", {
            "type": "Rule", "title": "t", "scope": "org", "id": "m1"})).startswith("recorded m1")
        assert _mcp_text(await mcp.call_tool("okl_record", {
            "type": "Rule", "title": "u", "scope": "org"})).startswith("recorded ")
        # ASSERT (2) — an existing id is refused, pointing only at okl_update: an agent is
        # not offered a one-step way to wipe a lesson's proof
        again = _mcp_text(await mcp.call_tool("okl_record", {
            "type": "Rule", "title": "x", "scope": "org", "id": "m1"}))
        assert again.startswith("NOT RECORDED") and "okl_update" in again, again
        assert "replace" not in again.lower(), again
        tool = next(t for t in await mcp.list_tools() if t.name == "okl_record")
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
        assert "replace" not in schema.get("properties", {}), schema

    asyncio.run(exercise())
    assert remote.store.get_node("m1").title == "t"


def test_an_id_with_a_slash_works_over_a_service(remote, capsys):
    """GET /node/{id} did not match an id holding "/", so show and update were a 404 over a
    service while they worked locally."""
    # ARRANGE
    assert main(["record", "--id", "auth/idor", "--type", "Rule", "--scope", "org",
                 "--title", "t"]) == 0
    capsys.readouterr()

    # ACT / ASSERT
    assert main(["show", "auth/idor"]) == 0
    assert "[auth/idor]" in capsys.readouterr().out
    assert main(["update", "auth/idor", "--fix", "g"]) == 0
    assert remote.store.get_node("auth/idor").fix == "g"


def test_a_service_update_with_a_wrong_type_is_refused_and_writes_nothing(remote):
    """/update took any JSON: ttl_days="x" was written, the reply was an error, and every
    later read of the lesson was a 500."""
    from okl import core

    # ARRANGE
    core.record(remote.store, id="l1", type="Rule", title="t", scope="org", fix="f")
    before = core.get(remote.store, "l1")

    # ACT
    bad = [remote.api.post("/update", json={"id": "l1", "fields": f})
           for f in ({"ttl_days": "x"}, {"tags": ["security"]}, {"nope": "x"})]

    # ASSERT — refused as the caller's error, nothing written, the lesson still reads
    assert [r.status_code for r in bad] == [422, 422, 422], [r.text for r in bad]
    assert core.get(remote.store, "l1") == before
    assert remote.api.get("/node/l1").status_code == 200
    # ASSERT — every write path refuses it, not just the service's model
    with pytest.raises(ValueError, match="ttl_days"):
        core.update(remote.store, "l1", ttl_days="x")
    assert core.get(remote.store, "l1") == before


def test_recording_an_id_against_a_service_too_old_to_refuse_is_refused(remote, capsys):
    """A service older than R1 ignores `replace` and overwrites: a new client must not
    let `okl record --id <existing>` wipe a lesson there, as R1's surfaces promise."""
    from okl import core

    # ARRANGE — a service without the routes R1 added, holding a proven lesson
    remote.app.router.routes[:] = [r for r in remote.app.router.routes
                                   if getattr(r, "path", "") not in ("/update", "/node/{node_id:path}")]
    core.record(remote.store, id="l1", type="Rule", title="t", scope="org", files="a.py")
    core.verify(remote.store, "l1", "`pytest -q` exit 0", commit=COMMIT)
    before = core.get(remote.store, "l1")
    capsys.readouterr()

    # ACT
    code = main(["record", "--id", "l1", "--type", "Rule", "--scope", "org", "--title", "x"])
    out, err = capsys.readouterr()

    # ASSERT — refused before anything was sent, naming the cause, the lesson untouched
    assert code == 2 and out == "", (code, out)
    assert "older" in err and "nothing was changed" in err, err
    assert core.get(remote.store, "l1") == before
    # ASSERT — show and update say the same, not a bare 404
    assert main(["show", "l1"]) == 2
    assert "older" in capsys.readouterr().err


def test_concurrent_updates_on_a_service_lose_nothing(remote):
    """Update reads, changes and writes back; two requests interleaving lost one change
    without an error (60 times in 150 rounds, measured against a live service)."""
    import threading

    # ARRANGE — and widen the window between an update's read and its write, which
    # in-process requests otherwise rarely land in
    import time

    from fastapi.testclient import TestClient

    from okl import core
    core.record(remote.store, id="l1", type="Rule", title="t", scope="org")
    read = remote.store._impl.get_node

    def slow_read(node_id):
        n = read(node_id)
        time.sleep(0.002)
        return n
    remote.store._impl.get_node = slow_read

    def hammer(field):
        api = TestClient(remote.app)
        for i in range(40):
            api.post("/update", json={"id": "l1", "fields": {field: f"{field}-{i}"}})

    # ACT
    threads = [threading.Thread(target=hammer, args=(f,)) for f in ("fix", "body", "symptom")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # ASSERT — every field holds its own last write
    n = remote.store.get_node("l1")
    assert (n.fix, n.body, n.symptom) == ("fix-39", "body-39", "symptom-39")


def test_update_keeps_proof_when_the_files_are_the_same_globs_reordered(repo, capsys):
    """The same globs in another order or spacing are the same files, as for okl seed."""
    # ARRANGE
    c = Client()
    c.record(id="l1", type="Rule", title="t", scope="repo", files="a.py,b.py")
    c.verify("l1", "`pytest -q` exit 0", commit=COMMIT)
    capsys.readouterr()

    # ACT
    assert main(["update", "l1", "--files", " b.py , a.py "]) == 0

    # ASSERT
    assert Client().get("l1")["verified_commit"] == COMMIT
    assert "proof kept" in capsys.readouterr().out


def test_a_files_change_keeps_the_stored_check_so_reverify_can_rerun_it(repo, capsys):
    """Clearing the stamp also threw away the command okl reverify exists to re-run."""
    # ARRANGE
    _proven_lesson()
    capsys.readouterr()

    # ACT
    assert main(["update", "price-server-side", "--files", "src/a.py,src/orders.py"]) == 0
    out = capsys.readouterr().out

    # ASSERT — the stamp is gone, the check that earned it is kept, and the hint says so
    after = Client().get("price-server-side")
    assert after["verified_at"] is None and after["verified_commit"] is None
    assert after["verified_by"] == "`pytest -q tests/test_orders.py` exit 0"
    assert "okl reverify" in out, out


def test_update_scope_repo_names_this_repo_and_is_refused_without_one(repo, capsys):
    """`repo` becomes repo:<name>; with no name to give it, it used to become repo:unknown
    and quietly leave every real repo's briefing."""
    from okl import core
    from okl.store import Store

    # ARRANGE
    Client().record(id="l1", type="Rule", title="t", scope="org")

    # ACT / ASSERT (1) — the CLI names this repo
    assert main(["update", "l1", "--scope", "repo"]) == 0
    assert Client().get("l1")["scope"] == "repo:r"

    # ACT / ASSERT (2) — with no repo anywhere, refused
    s = Store("sqlite:///:memory:")
    core.record(s, id="o1", type="Rule", title="t", scope="org")
    with pytest.raises(ValueError, match="repo name"):
        core.update(s, "o1", scope="repo")
    assert s.get_node("o1").scope == "org"


def test_retyping_a_vocabulary_lesson_withdraws_its_tag(tmp_path):
    """The declared-tag cache was cleared only when a Vocabulary was written, so retyping
    one left its tag accepted by a long-lived store and refused by a fresh one."""
    from okl import core
    from okl.store import Store

    # ARRANGE — a store that has declared `golang` and used it
    s = Store("sqlite:///:memory:")
    core.record(s, id="v-go", type="Vocabulary", title="golang", scope="org")
    core.record(s, type="Rule", title="uses it", scope="org", tags="golang")

    # ACT
    core.update(s, "v-go", type="Decision")

    # ASSERT — the same store no longer accepts the withdrawn tag
    with pytest.raises(ValueError, match="unknown tag"):
        core.record(s, type="Rule", title="x", scope="org", tags="golang")


def test_updating_a_seed_lesson_says_the_pack_owns_its_text(repo, capsys):
    """The briefing shows seed ids, and the next `okl seed` restores the pack's text."""
    # ARRANGE
    Client().record(id="seed:mypack:k1", type="Rule", title="t", scope="org")
    capsys.readouterr()

    # ACT
    assert main(["update", "seed:mypack:k1", "--fix", "refined"]) == 0

    # ASSERT
    assert "seed pack" in capsys.readouterr().err


def test_replace_needs_an_id_and_ttl_days_can_be_cleared(repo, capsys):
    """--replace without --id was ignored; --ttl-days "" was an argparse error."""
    # ACT / ASSERT (1)
    assert main(["record", "--replace", "--type", "Rule", "--scope", "repo", "--title", "t"]) == 2
    assert "needs --id" in capsys.readouterr().err

    # ACT / ASSERT (2)
    Client().record(id="l1", type="Rule", title="t", scope="repo", ttl_days=30)
    assert main(["update", "l1", "--ttl-days", ""]) == 0
    assert Client().get("l1")["ttl_days"] is None


def test_a_lost_answer_is_maybe_updated_and_a_failed_read_is_not(repo, capsys, monkeypatch):
    """The update was sent when its answer is lost, so it may have landed; the read before
    it sends nothing, so a failure there is NOT UPDATED."""
    import asyncio

    from okl.client import OKLNoAnswerError

    # ARRANGE
    Client().record(id="l1", type="Rule", title="t", scope="repo")
    capsys.readouterr()

    def lost(*a, **k):
        raise OKLNoAnswerError("OKL service unreachable at x: the request was sent, and ...")

    # ACT / ASSERT (1) — the update's answer is lost: MAYBE, from the CLI and from MCP
    monkeypatch.setattr("okl.client.Client.update", lost)
    assert main(["update", "l1", "--fix", "x"]) == 2
    assert "MAYBE UPDATED" in capsys.readouterr().err
    pytest.importorskip("mcp")
    from okl.mcp_server import _build
    out = _mcp_text(asyncio.run(_build().call_tool("okl_update", {"id": "l1", "fix": "x"})))
    assert out.startswith("MAYBE UPDATED"), out

    # ACT / ASSERT (2) — the read before it fails: NOT UPDATED
    monkeypatch.setattr("okl.client.Client.get", lost)
    assert main(["update", "l1", "--fix", "x"]) == 2
    assert "NOT UPDATED" in capsys.readouterr().err


def test_a_files_change_refreshes_the_committed_snapshot(repo, capsys, monkeypatch):
    """CI's drift gate reads okl-drift.json: an update that moved a proven lesson to other
    files left the snapshot calling it proven, green in CI and stale in the store."""
    # ARRANGE
    calls = []
    monkeypatch.setattr("okl.cli.lessons._refresh_snapshot",
                        lambda node, why="": calls.append((node["id"], why)))
    _proven_lesson()

    # ACT
    assert main(["update", "price-server-side", "--fix", "wording only"]) == 0
    assert main(["update", "price-server-side", "--files", "src/checkout.py"]) == 0

    # ASSERT — refreshed once, for the files change only
    assert calls == [("price-server-side", "its governed files changed")]
