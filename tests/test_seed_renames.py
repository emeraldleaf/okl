"""A renamed seed pack takes the records a store holds under its old name with it (#379).

A seed record's id is `seed:<pack>:<key>`. b28bf64 renamed ten bundled packs, keeping their keys,
so a store seeded before it held ids no refresh could find, and seeding a renamed pack stored
the same lessons a second time. core.PACK_RENAMES maps each old name, as its sha256, to the
current one; these tests register a made-up old name the same way, so they name no real one.
"""
import hashlib
import json

import pytest

from okl import core
from okl.cli import main
from okl.client import Client

OLD, NEW = "old-rag-pack", "rag-defects"
EVIDENCE = "`pytest -q tests/test_x.py` exit 0, matched 'passed' on commit {c} @ 2026-08-01T10:00Z"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repo with a local store, and OLD registered as a past name of NEW."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "interests": ["python-rag"]}))
    monkeypatch.setitem(core.PACK_RENAMES, hashlib.sha256(OLD.encode()).hexdigest(), NEW)
    return tmp_path


def _pack_nodes() -> list[dict]:
    return json.loads((core.bundled_seed_dir() / f"{NEW}.json").read_text())["nodes"]


def _seed_under_old_name(c: Client, keys: list[str]) -> None:
    """The store as it was before the rename: these records under the old pack name."""
    for node in _pack_nodes():
        if node["key"] in keys:
            fields = {k: v for k, v in node.items() if k != "key"}
            fields.setdefault("repo", None)
            c.record(id=f"seed:{OLD}:{node['key']}", **fields)


def _keys(n: int = 2) -> list[str]:
    return [node["key"] for node in _pack_nodes()[:n]]


def test_a_refresh_moves_old_named_records_to_the_renamed_pack_with_their_proof(repo, capsys):
    """Refresh found no pack for the old ids: it now refreshes them from the renamed pack, each
    under the pack's id with its verification and first creation date, and the old id is
    superseded by it, so nothing is briefed twice and the old id keeps its history."""
    # ARRANGE — two records under the old name, one of them proven
    c = Client()
    k1, k2 = _keys()
    _seed_under_old_name(c, [k1, k2])
    proven = c.verify(f"seed:{OLD}:{k1}", EVIDENCE.format(c="a" * 40), commit="a" * 40)
    old1 = next(n for n in c.all_nodes() if n.id == f"seed:{OLD}:{k1}")

    # ACT
    assert main(["seed", "--refresh"]) == 0
    capsys.readouterr()

    # ASSERT (1) — the pack's ids now hold them, the first with its proof and creation date
    nodes = {n.id: n for n in c.all_nodes()}
    new1, new2 = nodes[f"seed:{NEW}:{k1}"], nodes[f"seed:{NEW}:{k2}"]
    assert (new1.verified_at, new1.verified_by, new1.verified_commit) == (
        proven["verified_at"], proven["verified_by"], proven["verified_commit"])
    assert new1.created_at == old1.created_at
    assert new1.status not in ("superseded", "obsolete") and new2.status not in ("superseded", "obsolete")
    # (2) — each old id is superseded by its new one, with the reason logged
    for k in (k1, k2):
        old = nodes[f"seed:{OLD}:{k}"]
        assert old.status == "superseded"
        retired = c._local_store().retirements(old.id)
        assert retired[-1].by == f"seed:{NEW}:{k}" and "renamed" in retired[-1].reason
    # (3) — only the held records came across: a refresh imports nothing new
    assert sum(1 for i in nodes if i.startswith(f"seed:{NEW}:")) == 2

    # ACT / ASSERT (4) — a second refresh changes nothing
    assert main(["seed", "--refresh"]) == 0
    again = {n.id: (n.status, n.verified_at) for n in c.all_nodes()}
    assert again == {i: (n.status, n.verified_at) for i, n in nodes.items()}


def test_seeding_the_renamed_pack_into_an_old_store_stores_nothing_twice(repo, capsys):
    """Seeding a renamed pack stored each lesson again under its new id beside the old one.
    Now the old one steps aside, and a second seed adds nothing at all."""
    c = Client()
    k1, k2 = _keys()
    _seed_under_old_name(c, [k1, k2])

    assert main(["seed", NEW]) == 0
    live = [n.id for n in c.all_nodes() if n.status != "superseded"]
    # Every live record is the pack's own, one per key: the old two stepped aside.
    assert not [i for i in live if i.startswith(f"seed:{OLD}:")]
    assert len(live) == len(_pack_nodes())
    count = len(c.all_nodes())

    assert main(["seed", NEW]) == 0
    assert len(c.all_nodes()) == count


def test_a_store_holding_both_names_keeps_the_new_ids_own_proof(repo, capsys):
    """Seeded under both names before this fix: the new id is the lesson now, so it keeps its
    own proof, and the old one is superseded rather than carried over it."""
    c = Client()
    (k1,) = _keys(1)
    _seed_under_old_name(c, [k1])
    c.verify(f"seed:{OLD}:{k1}", EVIDENCE.format(c="a" * 40), commit="a" * 40)
    assert main(["seed", NEW]) == 0
    # The old id was superseded on that run; re-create the duplicate a pre-fix seed left.
    store = c._local_store()
    dup = store.get_node(f"seed:{OLD}:{k1}")
    dup.status = None
    store.add_node(dup)
    new_proof = c.verify(f"seed:{NEW}:{k1}", EVIDENCE.format(c="b" * 40), commit="b" * 40)

    assert main(["seed", NEW]) == 0

    nodes = {n.id: n for n in c.all_nodes()}
    assert nodes[f"seed:{NEW}:{k1}"].verified_commit == new_proof["verified_commit"] == "b" * 40
    assert nodes[f"seed:{OLD}:{k1}"].status == "superseded"


def test_a_retracted_record_stays_retracted_under_its_new_id(repo, capsys):
    """A team's decision travels with the lesson: one retracted under its old name is retracted
    under the new one, and the old id steps aside, so the briefing says AVOID once."""
    c = Client()
    (k1,) = _keys(1)
    _seed_under_old_name(c, [k1])
    c.retire(f"seed:{OLD}:{k1}", "wrong for this repo")

    assert main(["seed", "--refresh"]) == 0

    nodes = {n.id: n for n in c.all_nodes()}
    assert nodes[f"seed:{NEW}:{k1}"].status == "retracted"
    assert nodes[f"seed:{OLD}:{k1}"].status == "superseded"


def test_a_service_carries_and_supersedes_too(remote):
    """`okl seed` against a service sends `supersedes` in the record request. The request model
    drops a field it does not declare, silently, so without it the service stored a second
    copy and left the old one briefed."""
    c = Client()
    c.record(id="seed:old-p:k", type="Rule", title="t", scope="org", repo=None)
    c.record(id="seed:new-p:k", type="Rule", title="t", scope="org", repo=None,
             keep_verification=True, supersedes="seed:old-p:k")
    assert remote.store.get_node("seed:old-p:k").status == "superseded"
    assert remote.store.get_node("seed:new-p:k").status not in ("superseded", "obsolete")


def test_the_rename_map_names_only_bundled_packs_and_no_current_name():
    """Every rename leads to a bundled pack, and no key is the hash of a current pack's name,
    which would send a live pack's records to another."""
    bundled = core.bundled_packs()
    assert len(core.PACK_RENAMES) == 10
    assert set(core.PACK_RENAMES.values()) <= bundled
    current = {hashlib.sha256(p.encode()).hexdigest() for p in bundled}
    assert not current & set(core.PACK_RENAMES)
    assert all(core.current_pack(p) == p for p in bundled)


def test_old_named_records_of_a_renamed_pack_are_not_asked_for_triggers(repo):
    """A bundled pack's lessons ship their triggers, so the store's own lessons without any are
    what the briefing asks about. Records under a renamed pack's old name are the pack's."""
    c = Client()
    (k1,) = _keys(1)
    _seed_under_old_name(c, [k1])
    store = c._local_store()
    node = store.get_node(f"seed:{OLD}:{k1}")
    node.triggers = None
    store.add_node(node)
    assert f"seed:{OLD}:{k1}" not in {n.id for n in core.lessons_without_triggers(c.all_nodes())}


def test_a_record_already_moved_is_neither_carried_nor_retired_again():
    """`supersedes` naming a lesson that already stepped aside does nothing to it: a re-run logs
    no second retirement, and a new id does not inherit its superseded status, which would keep
    the new lesson out of every briefing. okl seed never passes one; a service client may."""
    from okl.store import Store
    store = Store("sqlite:///:memory:")
    core.record(store, id="seed:old-p:k", type="Rule", title="t", scope="org")
    core.record(store, id="seed:new-p:k", type="Rule", title="t", scope="org",
                keep_verification=True, supersedes="seed:old-p:k")

    core.record(store, id="seed:new-p:k", type="Rule", title="t", scope="org",
                keep_verification=True, supersedes="seed:old-p:k")
    core.record(store, id="seed:other-p:k", type="Rule", title="t", scope="org",
                keep_verification=True, supersedes="seed:old-p:k")

    assert len(store.retirements("seed:old-p:k")) == 1
    assert store.get_node("seed:other-p:k").status not in ("superseded", "obsolete")
