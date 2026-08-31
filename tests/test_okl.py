"""End-to-end tests: store round-trip, check bucketing, curation boundary,
the recurrence metric, seed ingestion, and (if fastapi is present) the service.
"""
import json
from pathlib import Path

import pytest

from okl import core
from okl.store import Node, Store


@pytest.fixture
def store():
    s = Store("sqlite:///:memory:")
    yield s
    s.close()


def test_node_roundtrip(store):
    nid = store.add_node(Node(type="Gate", title="import all class_paths", scope="org"))
    got = store.get_node(nid)
    assert got is not None and got.title == "import all class_paths" and got.scope == "org"


def test_bad_type_and_scope_rejected(store):
    with pytest.raises(ValueError):
        store.add_node(Node(type="Nonsense", title="x", scope="org"))
    with pytest.raises(ValueError):
        store.add_node(Node(type="Gate", title="x", scope="global"))


def test_check_buckets_gate_with_catches(store):
    d = core.record(store, type="Defect", title="rslearn class_path wrong", scope="org",
                    body="module paths written from memory", verified=True)
    g = core.record(store, type="Gate", title="check-scaffold-classpaths",
                    scope="org", body="import all 23 class_paths", verified=True)
    core.link(store, g, "CATCHES", d)
    res = core.check(store, repo="new-repo", task="scaffold rslearn model class_path")
    assert res["armed_gates"], "gate should surface for a matching task"
    assert any("rslearn class_path wrong" in c for c in res["armed_gates"][0]["catches"])


def test_curation_boundary_repo_scope_isolated(store):
    core.record(store, type="Rule", title="dotnet regex newline trap", scope="repo:dotnet-repo",
                body="$ matches before trailing newline")
    # another repo's check must NOT see dotnet-repo's repo-scoped quirk
    res = core.check(store, repo="the geospatial repo", task="regex newline trap validation")
    assert not res["rules"], "repo-scoped node must not leak into another repo's check"
    # but the owning repo does see it
    res2 = core.check(store, repo="dotnet-repo", task="regex newline trap validation")
    assert res2["rules"], "owning repo should see its own repo-scoped rule"


def test_org_scope_visible_everywhere(store):
    core.record(store, type="PriorArt", title="Evangelista 2018 the study basin", scope="org",
                status="live", body="THREAT: refutes novelty claim")
    res = core.check(store, repo="any-new-repo", task="the target species change mapping the study basin")
    assert res["threat_prior_art"], "org-scope prior art should reach every repo"


def test_staleness_demotes_not_deletes(store):
    old = Node(type="Rule", title="license present", scope="org", ttl_days=1,
               verified_at=0)  # verified at epoch 0 => long past TTL
    nid = store.add_node(old)
    n = store.get_node(nid)
    assert n.is_stale() is True


def test_recurrence_metric(store):
    d = core.record(store, type="Defect", title="class_path wrong", scope="org")
    g = core.record(store, type="Gate", title="classpath gate", scope="org")
    core.link(store, g, "CATCHES", d)
    assert store.recurrence_after_arming() == []          # nothing recurred yet
    # simulate recurrence in a repo that didn't arm the gate
    repo_node = core.record(store, type="Entity", title="dotnet-repo", scope="repo:dotnet-repo",
                            repo="dotnet-repo")
    core.link(store, repo_node, "RECURS_IN", d)
    rows = store.recurrence_after_arming()
    assert len(rows) == 1 and rows[0]["gate"] == "classpath gate"


def test_seed_file_loads(store, tmp_path, monkeypatch):
    seed = Path(__file__).resolve().parents[1] / "seed" / "geospatial-defects.json"
    if not seed.exists():
        pytest.skip("seed file not present")
    # drive core directly against the in-memory store (bypass Client file lookup)
    data = json.loads(seed.read_text())
    keymap = {}
    for node in data["nodes"]:
        node = {k: v for k, v in node.items() if not k.startswith("_")}
        key = node.pop("key", None)
        nid = core.record(store, **node)
        if key:
            keymap[key] = nid
    for e in data["edges"]:
        core.link(store, keymap.get(e["src"], e["src"]), e["rel"], keymap.get(e["dst"], e["dst"]))
    # a fresh repo scaffolding rslearn should get error #14's gate
    res = core.check(store, repo="brand-new-repo", task="scaffold an rslearn OlmoEarth model config class_path")
    assert res["armed_gates"], "seeded gate should arm for a new repo"
    md = core.render_check_for_agent(res)
    assert "class_path" in md.lower()


def test_service_check(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from okl.service import create_app
    s = Store("sqlite:///:memory:")
    d = core.record(s, type="Defect", title="temporal decoder axes", scope="org", verified=True)
    g = core.record(s, type="Gate", title="laptop dry-run decoder shapes", scope="org", verified=True)
    core.link(s, g, "CATCHES", d)
    app = create_app(store=s)
    client = TestClient(app)
    assert client.get("/health").json()["ok"] is True
    r = client.post("/check", json={"repo": "x", "task": "temporal segmentation decoder axes"})
    assert r.status_code == 200 and r.json()["armed_gates"]
    # validation errors are the caller's: 400 WITH the message, never a 500 (E2E finding —
    # an agent inventing tags got an opaque 500 and reported the service as down)
    bad = client.post("/record", json={"type": "Rule", "title": "t", "scope": "org", "tags": "ci,pinning"})
    assert bad.status_code == 400 and "vocabulary" in bad.json()["detail"]


# ---- new-feature tests: schema, router, drift, idempotent seed, coverage ----

def test_record_symptom_cause_fix_roundtrip(store):
    nid = core.record(store, type="Defect", title="price tamper", scope="org",
                      body="cause: trusts client price", symptom="DTO carries Price",
                      fix="compute server-side", verified=True)
    n = store.get_node(nid)
    assert n.symptom == "DTO carries Price" and n.fix == "compute server-side"


def test_check_router_actions(store):
    core.record(store, type="Defect", title="price tamper", scope="org",
                body="trusts client price", symptom="DTO carries Price",
                fix="compute server-side", verified=True)
    res = core.check(store, repo="r", task="add endpoint that sets a price")
    kinds = {a["kind"] for a in res["next_actions"]}
    assert "apply_fix" in kinds
    md = core.render_check_for_agent(res)
    assert "Do this" in md and "compute server-side" in md


def test_drift_fires_when_source_changes(store, tmp_path):
    import shutil
    import subprocess
    import time

    from okl import drift
    if shutil.which("git") is None:
        pytest.skip("git not available")
    rd = tmp_path / "repo"; rd.mkdir()
    def git(*a): return subprocess.run(["git","-C",str(rd),*a], capture_output=True)
    if git("init").returncode != 0:
        pytest.skip("git init blocked in this environment (e.g. sandbox git protection)")
    git("config","user.email","t@t.co"); git("config","user.name","t")
    src = rd / "orders.py"; src.write_text("x=1\n")
    if git("add","-A").returncode != 0 or git("commit","-m","init").returncode != 0:
        pytest.skip("git commit blocked in this environment")
    # verified now; no drift
    nid = core.record(store, type="Rule", title="orders rule", scope="org",
                      files="orders.py", verified=True)
    assert drift.detect_drift(store.all_nodes(), "r", str(rd)) == []
    time.sleep(1)
    src.write_text("x=2\n"); git("add","-A"); git("commit","-m","change")
    hits = drift.detect_drift(store.all_nodes(), "r", str(rd))
    assert len(hits) == 1 and hits[0].node_id == nid


def test_seed_is_idempotent(store, tmp_path):
    seed = tmp_path / "x-defects.json"
    seed.write_text(json.dumps({"nodes":[
        {"key":"a","type":"Defect","title":"A","scope":"org"},
        {"key":"b","type":"Gate","title":"B","scope":"org"}],
        "edges":[{"src":"B","rel":"CATCHES","dst":"a"}]}))
    from okl.seed import seed_from_file
    class _C:  # minimal client shim over the in-memory store
        repo="r"
        def record(self, **k): return core.record(store, **k)
        def link(self, s,r,d): return core.link(store, s, r, d)
    c=_C()
    seed_from_file(c, str(seed)); n1=len(store.all_nodes())
    seed_from_file(c, str(seed)); n2=len(store.all_nodes())
    assert n1 == n2 == 2, f"re-seed duplicated: {n1} -> {n2}"


# ---- subject tags: controlled vocabulary + interest filtering ----

def test_tags_roundtrip_and_vocabulary_enforced(store):
    nid = core.record(store, type="Defect", title="judge crash", scope="org",
                      tags="eval-integrity,data-quality")
    assert store.get_node(nid).tags == "eval-integrity,data-quality"
    with pytest.raises(ValueError):
        core.record(store, type="Defect", title="x", scope="org", tags="not-a-real-tag")


def test_check_filters_org_nodes_by_declared_interests(store):
    core.record(store, type="Defect", title="judge crash on eval run", scope="org",
                tags="eval-integrity", fix="lead with failure count")
    core.record(store, type="Defect", title="localStorage tokens on eval page", scope="org",
                tags="react,security")
    core.record(store, type="Rule", title="eval budget parity", scope="org")  # untagged
    core.record(store, type="Defect", title="local eval quirk", scope="repo:r",
                tags="react")  # own repo, off-interest tag
    res = core.check(store, repo="r", task="eval judge localStorage budget quirk",
                     interests=["eval-integrity", "python-rag"])
    titles = {d["title"] for d in res["relevant_defects"]} | {r["title"] for r in res["rules"]}
    assert "judge crash on eval run" in titles, "matching-tag org node must pass"
    assert "eval budget parity" in titles, "untagged org node must pass"
    assert "local eval quirk" in titles, "own repo-scoped node must pass regardless of tags"
    assert "localStorage tokens on eval page" not in titles, "off-interest org node must be dropped"
    # no interests declared -> nothing filtered
    res2 = core.check(store, repo="r", task="eval judge localStorage budget quirk")
    titles2 = {d["title"] for d in res2["relevant_defects"]}
    assert "localStorage tokens on eval page" in titles2


def test_init_wires_everything_mechanically(tmp_path, monkeypatch, capsys):
    """`okl init` must DO the wiring, not print instructions: hooks installed AND
    registered in settings.json (idempotently, preserving existing settings), CI verifier
    installed when git exists, loud warning when it doesn't (drift layer dead)."""
    import argparse
    import importlib.util

    from okl.cli import cmd_init
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".git").mkdir()  # cmd_init only checks for the directory's existence
    # pre-existing settings must survive the merge
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(
        {"model": "opus", "hooks": {"PreToolUse": [{"matcher": "Bash",
         "hooks": [{"type": "command", "command": "mine.sh"}]}]}}))
    args = argparse.Namespace(repo="wired", service=None, interests="security")
    assert cmd_init(args) == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["model"] == "opus", "unrelated settings must be preserved"
    pre = settings["hooks"]["PreToolUse"]
    assert any(h["command"] == "mine.sh" for e in pre for h in e["hooks"]), "existing hooks preserved"
    assert not any("okl" in h["command"] for e in pre for h in e["hooks"]), \
        "the briefing must NOT be a PreToolUse hook — its stdout never reaches the model"
    ups = settings["hooks"]["UserPromptSubmit"]
    assert any("userpromptsubmit-okl-check.sh" in h["command"] for e in ups for h in e["hooks"])
    assert any("stop-okl-encode.sh" in h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"])
    assert (tmp_path / ".claude" / "hooks" / "userpromptsubmit-okl-check.sh").exists()
    assert (tmp_path / ".github" / "workflows" / "okl-verify.yml").exists()
    if importlib.util.find_spec("mcp"):
        assert "okl" in json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    # idempotent: second run adds nothing
    assert cmd_init(args) == 0
    settings2 = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings2 == settings, "re-running init must not duplicate hook registrations"


def test_init_warns_without_git(tmp_path, monkeypatch, capsys):
    import argparse

    from okl.cli import cmd_init
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(repo="nogit", service=None, interests=None)
    assert cmd_init(args) == 0
    out = capsys.readouterr().out
    assert "not a git repository" in out and "DISABLED" in out
    assert not (tmp_path / ".github").exists()


def test_verify_stamps_only_from_evidence(store):
    nid = core.record(store, type="Rule", title="outputs must exist", scope="org")
    assert store.get_node(nid).verified_at is None
    with pytest.raises(ValueError):
        core.verify(store, nid, "   ")          # no evidence, no stamp
    with pytest.raises(ValueError):
        core.verify(store, "n_missing", "x")    # unknown node
    out = core.verify(store, nid, "`pytest -q` exit 0 @ 2026-08-09")
    n = store.get_node(nid)
    assert n.verified_at is not None and "pytest -q" in n.verified_by
    assert out["verified_by"] == n.verified_by


def test_cmd_verify_runs_the_check_first(tmp_path, monkeypatch, capsys):
    """The CLI half: exit != 0 -> no stamp; exit 0 without the expected signal -> no stamp
    (a step's own success report isn't enough); observed pass -> stamped with evidence."""
    import argparse

    from okl.cli import cmd_verify
    from okl.client import Client
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "t"}))
    nid = Client().record(type="Gate", title="g", scope="org")
    def ns(run, expect=None):
        return argparse.Namespace(node_id=nid, run=run, expect=expect, timeout=60)
    assert cmd_verify(ns("false")) == 1                       # failing check
    assert cmd_verify(ns("echo done", expect="238 files")) == 1   # exit 0 but no success signal
    fresh = Client()  # re-read the store after the CLI's writes
    assert fresh.all_nodes()[0].verified_at is None, "no stamp without an observed pass"
    assert cmd_verify(ns("echo wrote 3 files", expect="3 files")) == 0
    n = Client().all_nodes()[0]
    assert n.verified_at is not None and "echo wrote 3 files" in n.verified_by


def test_postgres_search_is_ranked_fulltext():
    """The Postgres backend must mirror the FTS5 path: OR-permissive websearch query,
    ts_rank ordering, ILIKE only for blank queries. (SQL shape asserted via a fake
    connection — live-Postgres coverage still needs a real server/Testcontainers.)"""
    from okl.store import _NODE_COLS, _pg_ts_query, _PostgresBackend
    assert _pg_ts_query("add an LLM judge!") == "add OR an OR LLM OR judge"
    assert _pg_ts_query("   ") == ""
    captured = {}
    class _Cur:
        description = [type("D", (), {"name": n}) for n in _NODE_COLS]
        def execute(self, sql, params): captured["sql"], captured["params"] = sql, params
        def fetchall(self): return []
        def __enter__(self): return self
        def __exit__(self, *a): return False
    class _Conn:
        def cursor(self): return _Cur()
    b = _PostgresBackend.__new__(_PostgresBackend)  # bypass __init__ (no psycopg/server here)
    b.conn = _Conn()
    b.search("llm judge eval", None, ["Defect"], 5)
    assert "websearch_to_tsquery" in captured["sql"] and "ts_rank" in captured["sql"]
    assert "ORDER BY" in captured["sql"] and "ILIKE" not in captured["sql"]
    b.search("   ", None, None, 5)
    assert "ILIKE" in captured["sql"] and "ts_rank" not in captured["sql"]


def test_seed_node_without_repo_stays_unattributed(store, tmp_path, capsys):
    seed = tmp_path / "y-defects.json"
    seed.write_text(json.dumps({"nodes": [
        {"key": "a", "type": "Gate", "title": "A", "scope": "org"}], "edges": []}))
    from okl.seed import seed_from_file
    class _C:  # mimics Client.record's repo default, the mislabeling path
        repo = "current-repo"
        def record(self, **k):
            k.setdefault("repo", self.repo)
            return core.record(store, **k)
        def link(self, s, r, d): return core.link(store, s, r, d)
    seed_from_file(_C(), str(seed))
    (n,) = store.all_nodes()
    assert n.repo is None, "seed node without repo must not inherit the seeding repo"
    assert "no 'repo'" in capsys.readouterr().err

def test_init_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    """--dry-run must list what init would touch and leave the filesystem alone.
    Anyone about to let a package install executable hooks and a CI workflow into
    their repo should be able to see the list first."""
    import argparse

    from okl.cli import cmd_init
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".git").mkdir()
    before = sorted(p.name for p in tmp_path.iterdir())
    args = argparse.Namespace(repo="demo", service=None, interests=None, dry_run=True)
    assert cmd_init(args) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    for expected in ("hooks/userpromptsubmit-okl-check.sh", "settings.json",
                     ".github/workflows/okl-verify.yml", ".okl/config.json"):
        assert expected in out, f"dry run must disclose {expected}"
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "dry run wrote something"
    assert not (tmp_path / ".okl").exists()
    assert not (tmp_path / ".github").exists()
