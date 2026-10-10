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

    # ASSERT — a check of other files proves nothing about these, so the stamp goes
    assert code == 0
    after = Client().get("price-server-side")
    assert after["files"] == "src/checkout.py"
    assert after["verified_at"] is None and after["verified_by"] is None
    assert after["verified_commit"] is None
    assert "proof cleared" in out and "okl verify price-server-side" in out, out


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
