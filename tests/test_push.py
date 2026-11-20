"""`okl push`: a repo's lessons copied to a deployed okl service, one way (#504).

The review on a pull request reads only okl's seed packs in CI, since a runner cannot see the
gitignored local store. A deployed service holds a copy that the local store pushes to, and CI
reads the copy. These run the real client against the real service app in this process.
"""
import json
import os
import subprocess
from dataclasses import asdict

import pytest

from okl import core
from okl.cli import main
from okl.cli.install import _push_refusal
from okl.client import Client
from okl.store import Edge, Node, Store

TARGET = "https://okl.test"
GIT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


@pytest.fixture
def deployed(tmp_path, monkeypatch, serve_in_process):
    """A deployed service that needs the token `s3cret`, with an empty store, and a repo set up
    with okl in the current directory whose local store holds the lessons to push."""
    from okl.service import create_app
    monkeypatch.setenv("OKL_TOKEN", "s3cret")
    copy = Store("sqlite:///:memory:")
    seen = serve_in_process(create_app(store=copy))
    monkeypatch.delenv("OKL_TOKEN")
    repo = tmp_path / "repo"
    (repo / ".okl").mkdir(parents=True)
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.chdir(repo)
    seen.copy, seen.repo = copy, repo
    return seen


def _fill(local: Client) -> dict[str, str]:
    """A declared tag and a lesson that carries it, a retired lesson, one with proof, and an edge."""
    store = local._local_store()
    core.record(store, type="Vocabulary", title="golang", scope="org")
    tagged = core.record(store, type="Rule", title="Close the response body", scope="org", tags="golang",
                         fix="defer resp.Body.Close()", id="close-the-body")
    wrong = core.record(store, type="Rule", title="Always retry", scope="repo:r", id="always-retry")
    core.retire(store, wrong, "it retried a payment")
    store.add_node(Node(id="proven", type="Rule", title="Pin the linter", scope="org", verified_at=1_700_000_000_000,
                        verified_by="`ruff --version` exit 0", verified_commit="abc1234", created_at=1_600_000_000_000))
    store.add_edge(Edge(src=tagged, rel="SUPERSEDES", dst=wrong, created_at=1_650_000_000_000))
    return {"tagged": tagged, "wrong": wrong}


def _rows(store: Store) -> list[dict]:
    return sorted((asdict(n) for n in store.all_nodes()), key=lambda r: r["id"])


def test_a_push_copies_every_row_as_the_local_store_holds_it(deployed, capsys):
    """Each lesson arrives whole: its id, times, status and proof as the local store has them,
    which `record` on the service would have stamped anew. The tag's declaration goes first, or
    the lesson that carries the tag would be refused. The target and token are remembered, and
    the token is never printed."""
    local = Client()
    _fill(local)
    assert main(["push", "--to", TARGET, "--token", "s3cret"]) == 0
    out = capsys.readouterr().out
    assert "pushed 4 lesson(s) and 1 edge(s) to okl.test" in out and "s3cret" not in out
    assert _rows(deployed.copy) == _rows(local._local_store())
    assert core.all_edges(deployed.copy) == core.all_edges(local._local_store())
    assert deployed.copy.get_node("always-retry").status in ("retracted", "obsolete", "superseded")
    cfg = json.loads((deployed.repo / ".okl" / "config.json").read_text())
    assert (cfg["push_url"], cfg["push_token"]) == (TARGET, "s3cret")
    if os.name == "posix":      # a config holding a token is a credential file: its owner's alone
        assert (deployed.repo / ".okl" / "config.json").stat().st_mode & 0o077 == 0
    assert all(h.get("authorization") == "Bearer s3cret" for h in deployed.headers)


def test_a_second_push_sends_only_what_changed(deployed, capsys):
    """A push with nothing new is two reads and no write, so it can run before every git push.
    After one lesson changes, a bare `okl push` sends that one to the remembered target."""
    local = Client()
    ids = _fill(local)
    assert main(["push", "--to", TARGET, "--token", "s3cret"]) == 0
    writes = len(deployed.sent)
    assert main(["push"]) == 0
    assert "pushed 0 lesson(s) and 0 edge(s)" in capsys.readouterr().out and len(deployed.sent) == writes
    core.update(local._local_store(), ids["tagged"], fix="defer resp.Body.Close(), after the error check")
    assert main(["push"]) == 0
    assert "pushed 1 lesson(s) and 0 edge(s) to okl.test; 3 lesson(s) there already matched" in capsys.readouterr().out
    assert deployed.copy.get_node(ids["tagged"]).fix.endswith("after the error check")
    assert _rows(deployed.copy) == _rows(local._local_store())


def test_a_push_larger_than_one_request_still_declares_its_tags_first(deployed):
    """A push goes in requests of a hundred rows, each inside the client's timeout. The service
    writes a declaration first within a request; across requests only the client can, or a lesson
    in the first request is refused for a tag whose declaration is in the second."""
    store = Client()._local_store()
    store.add_node(Node(id="zz-declared-last-by-id", type="Vocabulary", title="golang", scope="org"))
    for i in range(120):
        store.add_node(Node(id=f"a-{i:03d}", type="Rule", title=f"lesson {i}", scope="org", tags="golang"))
    assert main(["push", "--to", TARGET, "--token", "s3cret"]) == 0
    assert len(deployed.copy.all_nodes()) == 121
    batches = [len(body["nodes"]) for path, body in deployed.sent if path == "/sync"]
    assert batches == [100, 21] and deployed.sent[0][1]["nodes"][0]["type"] == "Vocabulary"


def test_ci_reads_the_pushed_lessons_through_the_service(deployed, tmp_path, monkeypatch, capsys):
    """What the push is for: with only the service's URL and token, as a runner has them, the
    review's listing (`okl check --change --format json`) names exactly the lessons the local
    store would list, and `okl show` prints one. Before, CI could list the seed packs alone."""
    local = Client()
    ids = _fill(local)
    here = {e["id"] for e in core.review_menu(local._local_store().all_nodes(), "r", None)}
    assert {ids["tagged"], "proven"} <= here
    assert main(["push", "--to", TARGET, "--token", "s3cret"]) == 0
    runner = tmp_path / "runner"; runner.mkdir()
    for args in (["init", "-q", "-b", "main"], [*GIT, "commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", "-C", str(runner), *args], check=True)
    (runner / "fetch.go").write_text("package main\n")
    monkeypatch.chdir(runner)
    monkeypatch.setenv("OKL_SERVICE_URL", TARGET); monkeypatch.setenv("OKL_TOKEN", "s3cret")
    capsys.readouterr()
    assert main(["check", "--change", "main", "--repo", "r", "--format", "json"]) == 0
    assert {e["id"] for e in json.loads(capsys.readouterr().out)["lessons"]} == here
    assert main(["show", "--", ids["tagged"]]) == 0
    assert "defer resp.Body.Close()" in capsys.readouterr().out


def test_a_dry_run_sends_and_remembers_nothing(deployed, capsys):
    """`--dry-run` reads the service to count what differs, and writes nothing to it or the config."""
    _fill(Client())
    assert main(["push", "--to", TARGET, "--token", "s3cret", "--dry-run"]) == 0
    assert "would send 4 lesson(s) and 1 edge(s) to okl.test" in capsys.readouterr().out
    assert deployed.sent == [] and deployed.copy.all_nodes() == []
    assert "push_url" not in json.loads((deployed.repo / ".okl" / "config.json").read_text())


def test_a_push_never_sends_another_services_token(deployed, monkeypatch):
    """OKL_TOKEN belongs to the service a repo reads. A push that honoured it would hand that
    token to the push target; it sends the one named for the target, and none when none is."""
    _fill(Client())
    monkeypatch.setenv("OKL_TOKEN", "the-other-services-token")
    assert main(["push", "--to", TARGET, "--token", "s3cret"]) == 0
    assert {h.get("authorization") for h in deployed.headers} == {"Bearer s3cret"}
    deployed.headers.clear()
    assert main(["push", "--to", TARGET, "--token", "wrong"]) == 2      # a 401 is a refusal, not an outage
    assert {h.get("authorization") for h in deployed.headers} == {"Bearer wrong"}


def test_push_refuses_where_it_cannot_or_must_not_run(deployed, monkeypatch, capsys):
    """Exit 2, the reason on stderr, nothing on stdout, nothing sent and nothing remembered."""
    _fill(Client())
    cases = {(): "no service to push to", ("--to", "http://okl.example"): "unencrypted",
             ("--to", "ftp://okl.example"): "must be an https:// URL", ("--to", "okl.example"): "must be an https:// URL"}
    for args, reason in cases.items():
        assert main(["push", *args]) == 2, args
        said = capsys.readouterr()
        assert said.out == "" and reason in said.err, (args, said.err)
    assert deployed.sent == [] and deployed.headers == []
    assert "push_url" not in json.loads((deployed.repo / ".okl" / "config.json").read_text())
    # http is taken for this machine only, where nothing crosses a network.
    assert _push_refusal("http://127.0.0.1:8080") is None and _push_refusal("http://localhost:8080") is None
    assert _push_refusal(TARGET) is None
    # A repo that reads a shared service has no local store to push.
    monkeypatch.setenv("OKL_SERVICE_URL", "https://another.test")
    assert main(["push", "--to", TARGET]) == 2
    assert "no local store to push" in capsys.readouterr().err


def test_a_service_too_old_to_take_a_push_says_so(deployed, serve_in_process, capsys):
    """A service from before /edges and /sync answers 404, which must not read as "pushed nothing"."""
    from fastapi import FastAPI
    old = FastAPI()
    old.get("/nodes")(lambda: {"nodes": []})
    serve_in_process(old)
    _fill(Client())
    assert main(["push", "--to", TARGET]) == 2
    said = capsys.readouterr()
    assert said.out == "" and "older than this okl client" in said.err and "takes a push" in said.err


def test_the_service_refuses_a_malformed_row_and_names_it(deployed):
    """An import validates as any write does, and says which row it would not take."""
    store = deployed.copy
    good = asdict(Node(id="ok", type="Rule", title="t", scope="org"))
    assert core.import_rows(store, [{**good, "a_field_from_a_newer_okl": 1}], []) == {"nodes": 1, "edges": 0}
    for bad, reason in (({**good, "id": ""}, "has no id"), ({**good, "id": "x", "tags": "not-a-tag"}, "'x'"),
                        ({"id": "y", "scope": "org"}, "'y' is not a whole row")):
        with pytest.raises(ValueError, match=reason):
            core.import_rows(store, [bad], [])
    with pytest.raises(ValueError, match="has no rel"):
        core.import_rows(store, [], [{"src": "a", "dst": "b", "created_at": 1}])
    with pytest.raises(ValueError, match="unknown edge relation"):
        core.import_rows(store, [], [{"src": "a", "rel": "LIKES", "dst": "b", "created_at": 1}])
    with pytest.raises(ValueError, match="at most"):
        core.import_rows(store, [good] * (core.IMPORT_MAX_ROWS + 1), [])
    r = deployed.api.post("/sync", json={"nodes": [{**good, "id": "x", "tags": "not-a-tag"}]},
                          headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 400 and "'x'" in r.json()["detail"]
    assert deployed.api.post("/sync", json={"nodes": []}).status_code == 401
    assert deployed.api.get("/edges").status_code == 401
    assert os.environ.get("OKL_TOKEN") is None
