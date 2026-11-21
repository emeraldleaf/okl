"""The committed lessons export: `okl export --lessons` and the read-only store that opens it.

A CI runner cannot see the gitignored store, so the review on a pull request read okl's bundled
packs alone. A repo that exports its lessons to okl-lessons.jsonl and commits the file gives CI
every lesson, with nothing hosted: OKL_DATABASE_URL=lessons:///<path> opens the file as a store
that answers every read and takes no write.
"""
import json
import subprocess
from dataclasses import asdict

import pytest

from okl import core
from okl.cli import main
from okl.client import Client
from okl.store import LESSONS_FILE, Edge, Node, Store, dump_lessons, load_lessons

GIT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
PROOF = ("verified_at", "verified_by", "verified_commit")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo set up with okl, in the current directory, holding: a declared tag and a lesson
    that carries it, a lesson with proof, a retracted lesson, and one with text outside ASCII."""
    root = tmp_path / "repo"
    (root / ".okl").mkdir(parents=True)
    (root / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.chdir(root)
    store = Client()._local_store()
    core.record(store, type="Vocabulary", title="golang", scope="org", id="zz-vocab")
    core.record(store, type="Rule", title="Close the response body", scope="org", tags="golang",
                fix="defer resp.Body.Close()", id="close-the-body")
    store.add_node(Node(id="proven", type="Rule", title="Pin the linter", scope="org", verified_at=1_700_000_000_000,
                        verified_by="`ruff --version` exit 0", verified_commit="abc1234", created_at=1_600_000_000_000))
    core.record(store, type="Rule", title="Always retry", scope="repo:r", id="always-retry")
    core.retire(store, "always-retry", "it retried a payment")
    core.record(store, type="Defect", title="Naïve café élan — 中文", scope="org", id="unicode", symptom="it said “done”")
    return root


def _exported(root):
    assert main(["export", "--lessons"]) == 0
    return root / LESSONS_FILE


def test_the_export_is_one_sorted_line_a_lesson_without_proof(repo, capsys):
    """A header, then every lesson in id order, one JSON object a line, so a change to one lesson
    is a one-line diff. Proof is left out: it changes at each re-verification, which would rewrite
    the file every time, and the committed drift snapshot already carries it."""
    path = _exported(repo)
    said = capsys.readouterr().out
    assert "5 lesson(s), without their proof" in said and "lessons:///" in said
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"okl_lessons": 1, "repo": "r"}
    rows = [json.loads(x) for x in lines[1:]]
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows) and len(rows) == 5
    assert not any(k in r for r in rows for k in PROOF)
    assert not any(v is None for r in rows for v in r.values()), "an empty field is left out, not written as null"
    assert "Naïve café élan — 中文" in path.read_text(encoding="utf-8"), "text is kept readable, not escaped"
    # Derived: the same store writes the same bytes, and a re-verification changes none of them.
    before = path.read_bytes()
    store = Client()._local_store()
    core.verify(store, "close-the-body", evidence="`go vet` exit 0", commit="def5678")
    assert main(["export", "--lessons"]) == 0 and path.read_bytes() == before


def test_the_export_opens_as_a_store_that_holds_the_same_lessons(repo):
    """Every lesson reads back as the store holds it, its proof aside; a lesson carrying a declared
    tag is accepted because its declaration is read first, wherever its id sorts."""
    path = _exported(repo)
    mine = {n.id: {k: v for k, v in asdict(n).items() if k not in PROOF} for n in Client()._local_store().all_nodes()}
    copy = Store(f"lessons:///{path}")
    try:
        assert copy.read_only and copy.url.startswith("lessons:///")
        assert {n.id: {k: v for k, v in asdict(n).items() if k not in PROOF} for n in copy.all_nodes()} == mine
        assert all(n.verified_at is None and n.verified_by is None for n in copy.all_nodes())
        assert [n.id for n in copy.search("response body", limit=3)][:1] == ["close-the-body"], "it is searchable"
        assert copy.declared_tags() == {"golang"}
    finally:
        copy.close()


def test_an_export_takes_no_write(repo, monkeypatch, capsys):
    """A lesson recorded into the export would vanish with the process while the command said it
    landed, and the file is derived from the author's store, never the other way. Each lesson
    write is refused, by the store and at the command line, and the file is left as it was."""
    path = _exported(repo)
    before = path.read_bytes()
    copy = Store(f"lessons:///{path}")
    try:
        for write in (lambda: copy.add_node(Node(type="Rule", title="t", scope="org")),
                      lambda: copy.add_edge(Edge(src="a", rel="SUPERSEDES", dst="b")),
                      lambda: copy.log_retirement("proven", "retracted", "wrong"),
                      lambda: copy.log_check("proven", True, "true", "exit 0")):
            with pytest.raises(ValueError, match="read-only"):
                write()
        assert len(copy.all_nodes()) == 5
    finally:
        copy.close()
    monkeypatch.setenv("OKL_DATABASE_URL", f"lessons:///{path}")
    capsys.readouterr()
    for args in (["record", "--type", "Rule", "--title", "t", "--scope", "org"],
                 ["update", "proven", "--title", "changed"], ["retire", "proven", "--reason", "wrong"],
                 ["verify", "proven", "--run", "true", "--expect", ""]):
        assert main(args) == 2, args
        said = capsys.readouterr()
        assert said.out == "" and "read-only" in said.err and "okl export --lessons" in said.err, (args, said.err)
    assert path.read_bytes() == before


def test_ci_lists_and_shows_the_lessons_from_the_export_alone(repo, tmp_path, monkeypatch, capsys):
    """What the export is for. On a runner, with the checkout and no store, the review's listing
    (`okl check --change --format json`) names exactly the lessons the author's store lists, and
    `okl show` prints one whole. Its proof line says the export does not carry proof, where "not
    proven yet" would have told the reader a verified lesson has no check behind it."""
    path = _exported(repo)
    here = {e["id"] for e in core.review_menu(Client()._local_store().all_nodes(), "r", None)}
    assert {"close-the-body", "proven", "unicode"} <= here
    runner = tmp_path / "runner"; runner.mkdir()
    for args in (["init", "-q", "-b", "main"], [*GIT, "commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", "-C", str(runner), *args], check=True)
    (runner / "fetch.go").write_text("package main\n")
    monkeypatch.chdir(runner)
    monkeypatch.setenv("OKL_DATABASE_URL", f"lessons:///{path}")
    capsys.readouterr()
    assert main(["check", "--change", "main", "--repo", "r", "--format", "json"]) == 0
    assert {e["id"] for e in json.loads(capsys.readouterr().out)["lessons"]} == here
    assert main(["show", "--", "proven"]) == 0
    shown = capsys.readouterr().out
    assert "Pin the linter" in shown and "proof: not in this export" in shown and "not proven yet" not in shown
    assert main(["check", "--task", "close the response body in the go client", "--repo", "r"]) == 0
    assert "close-the-body" in capsys.readouterr().out, "a briefing reads it too"


def test_a_lesson_written_refreshes_the_export_where_the_repo_has_one(repo, capsys):
    """A repo opts in by exporting once. From then on a lesson recorded, updated or retired
    rewrites the file and says so, or the next review in CI would read lessons as they were;
    `okl record` says it on stderr, since its stdout is the bare id. A repo with no export gets
    none made for it."""
    assert main(["record", "--type", "Rule", "--title", "Before any export", "--scope", "org", "--id", "early",
                 "--trigger", "x"]) == 0
    said = capsys.readouterr()
    assert said.out.strip() == "early" and "refreshed" not in said.err and not (repo / LESSONS_FILE).exists()
    path = _exported(repo)
    capsys.readouterr()
    assert main(["record", "--type", "Rule", "--title", "Wrap the error", "--scope", "org", "--id", "wrap-it",
                 "--trigger", "x"]) == 0
    said = capsys.readouterr()
    assert said.out.strip() == "wrap-it" and f"refreshed {LESSONS_FILE}" in said.err
    assert '"id": "wrap-it"' in path.read_text()
    assert main(["update", "wrap-it", "--fix", "use %w"]) == 0
    assert f"refreshed {LESSONS_FILE}" in capsys.readouterr().out and '"fix": "use %w"' in path.read_text()
    assert main(["retire", "wrap-it", "--reason", "it hid the cause"]) == 0
    assert f"refreshed {LESSONS_FILE}" in capsys.readouterr().out
    row = next(json.loads(x) for x in path.read_text().splitlines() if '"id": "wrap-it"' in x)
    assert row["status"] == "retracted"
    assert main(["export", "--lessons", "--check"]) == 0


def test_the_check_says_when_the_export_is_behind_the_store(repo, capsys):
    """`--check` writes nothing: 0 when the file is what the store would write, 1 when a lesson
    changed past it (a path that wrote to the store without the client), for a hook or a gate."""
    path = _exported(repo)
    assert main(["export", "--lessons", "--check"]) == 0
    before = path.read_bytes()
    Client()._local_store().add_node(Node(id="behind", type="Rule", title="written past the client", scope="org"))
    capsys.readouterr()
    assert main(["export", "--lessons", "--check"]) == 1
    said = capsys.readouterr()
    assert said.out == "" and "is not what this store would write" in said.err and path.read_bytes() == before
    path.unlink()
    assert main(["export", "--lessons", "--check"]) == 1, "a missing export is not a current one"
    assert main(["export", "--drift", "--check"]) == 2
    assert "--check goes with --lessons" in capsys.readouterr().err
    with pytest.raises(SystemExit) as both:
        main(["export", "--drift", "--lessons"])
    assert both.value.code == 2


def test_a_file_that_is_not_an_export_is_refused_and_named(repo, tmp_path, monkeypatch, capsys):
    """The export is read from a pull request's checkout, so it can hold anything. A file that is
    not one, a line that is not a lesson, a lesson that would be refused as a write, and a missing
    file each stop the command with exit 2 and one line that says which."""
    good = _exported(repo).read_text(encoding="utf-8").splitlines()
    cases = {"not json at all\n": "is not a lessons export",
             json.dumps({"some": "other file"}) + "\n": "is not a lessons export",
             "\n".join([good[0], "{broken"]) + "\n": "line 2 is not a lesson",
             "\n".join([good[0], good[1], json.dumps({"id": "x", "scope": "org"})]) + "\n": "line 3 is not a lesson",
             "\n".join([good[0], json.dumps({"id": "y", "type": "Rule", "title": "t", "scope": "org", "tags": "nope"})])
             + "\n": "lesson 'y'"}
    bad = tmp_path / LESSONS_FILE
    monkeypatch.setenv("OKL_DATABASE_URL", f"lessons:///{bad}")
    capsys.readouterr()
    for text, reason in cases.items():
        bad.write_text(text)
        assert main(["search", "anything"]) == 2, text
        said = capsys.readouterr()
        assert said.out == "" and reason in said.err and "Traceback" not in said.err, (text, said.err)
    bad.unlink()
    assert main(["search", "anything"]) == 2
    assert "cannot be read" in capsys.readouterr().err
    with pytest.raises(ValueError, match="line 2 is not a lesson"):
        load_lessons(good[0] + "\n[1, 2]\n")
    # Proof written into the file by hand is not read: a stamp comes from a check that ran, and a
    # pull request could otherwise mark any lesson verified by editing a line (lesson n_31bde92d9003).
    claimed = json.dumps({"id": "z", "type": "Rule", "title": "t", "scope": "org", "verified_at": 1_700_000_000_000,
                          "verified_by": "trust me", "verified_commit": "abc1234"})
    (node,) = load_lessons(good[0] + "\n" + claimed + "\n")
    assert (node.verified_at, node.verified_by, node.verified_commit) == (None, None, None)
    assert dump_lessons(load_lessons("\n".join(good) + "\n"), "r") == "\n".join(good) + "\n", "a round trip changes nothing"


def test_a_pack_and_the_mcp_tools_keep_the_export_in_step(repo, capsys):
    """Two writers that do not go through the command line's record: a seed pack writes its
    lessons straight to the store, and an agent records through the MCP tools. Each refreshes the
    export where the repo has one, and says so: the pack on its output, the tool in its reply,
    since the agent is the one who can commit the file."""
    from pathlib import Path

    from okl.mcp_server import _export_note
    path = _exported(repo)
    capsys.readouterr()
    pack = Path(__file__).resolve().parents[1] / "seed" / "ci-security.json"
    assert main(["seed", str(pack)]) == 0
    assert f"refreshed {LESSONS_FILE}" in capsys.readouterr().out
    assert "seed:ci-security:" in path.read_text() and main(["export", "--lessons", "--check"]) == 0
    client = Client()
    assert _export_note(client) == ""
    client.record(type="Rule", title="Recorded by an agent", scope="org", id="by-agent")
    assert LESSONS_FILE in _export_note(client) and "commit that file" in _export_note(client)
    assert '"id": "by-agent"' in path.read_text()
