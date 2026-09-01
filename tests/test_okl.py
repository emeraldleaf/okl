"""End-to-end tests for the knowledge layer.

Every test follows ARRANGE / ACT / ASSERT with a short story per phase, so a reader
can learn the contract being checked without opening the code under test. Where a test
guards a security boundary, an ordering rule, or a "silence is not safety" invariant,
the assertions are numbered and each says which failure it prevents.
"""
import json
from pathlib import Path

import pytest

from okl import core
from okl.store import Node, Store


@pytest.fixture
def store():
    """A throwaway store per test.

    `sqlite:///:memory:` keeps the database in RAM, so tests never touch a real file,
    never see each other's records, and run in milliseconds. The `yield` hands it to the
    test; everything after the yield is teardown that pytest runs even if the test fails.
    """
    s = Store("sqlite:///:memory:")
    yield s
    s.close()


def test_node_roundtrip(store):
    """A record written to the store comes back unchanged. The foundation everything
    else assumes: if this breaks, every other test is meaningless."""
    # ARRANGE / ACT — write one record. add_node returns the id the store assigned it.
    nid = store.add_node(Node(type="Gate", title="import all class_paths", scope="org"))

    # ACT — read it back by that id
    got = store.get_node(nid)

    # ASSERT — the record exists and its fields survived the trip intact
    assert got is not None, "a record written must be findable by the id we were given"
    assert got.title == "import all class_paths"
    assert got.scope == "org"


def test_bad_type_and_scope_rejected(store):
    """Type and scope are closed vocabularies, enforced at write time.

    Why it matters: `check` routes records by type and filters them by scope. A typo in
    either would produce a record that is stored but never retrieved — invisible, and
    worse than a loud failure, because the author believes the rule is protecting them.
    """
    # ARRANGE / ACT / ASSERT (1) — an unknown type is refused
    with pytest.raises(ValueError):
        store.add_node(Node(type="Nonsense", title="x", scope="org"))

    # ARRANGE / ACT / ASSERT (2) — scope must be "org" or "repo:<name>"; "global" is neither
    with pytest.raises(ValueError):
        store.add_node(Node(type="Gate", title="x", scope="global"))


def test_check_buckets_gate_with_catches(store):
    """A gate surfaced in a briefing arrives with the defect it catches attached.

    This is what makes a briefing actionable rather than bossy: "run this check" is an
    order, but "run this check, because it catches THIS bug" is a reason. The link is
    what carries the reason, so the briefing must follow it.
    """
    # ARRANGE — a defect, and the automated gate that catches it, joined by a CATCHES edge
    d = core.record(store, type="Defect", title="rslearn class_path wrong", scope="org",
                    body="module paths written from memory", verified=True)
    g = core.record(store, type="Gate", title="check-scaffold-classpaths",
                    scope="org", body="import all 23 class_paths", verified=True)
    core.link(store, g, "CATCHES", d)

    # ACT — a task whose words overlap both records
    res = core.check(store, repo="new-repo", task="scaffold rslearn model class_path")

    # ASSERT (1) — the gate was routed into the armed_gates bucket, not lost among rules
    assert res["armed_gates"], "gate should surface for a matching task"
    # ASSERT (2) — and the briefing walked the CATCHES edge to explain WHY it is armed
    assert any("rslearn class_path wrong" in c for c in res["armed_gates"][0]["catches"])


def test_curation_boundary_repo_scope_isolated(store):
    """Scope is the governance boundary, and it holds in both directions.

    This is the single rule that keeps a shared store usable. Without it, one project's
    quirks flood every other project's briefings, people stop reading them, and the whole
    layer becomes noise. The test therefore checks BOTH directions: it must not leak, and
    it must still reach its owner.
    """
    # ARRANGE — a rule true only of one repo, recorded with repo: scope
    core.record(store, type="Rule", title="dotnet regex newline trap", scope="repo:dotnet-repo",
                body="$ matches before trailing newline")

    # ACT (1) — a DIFFERENT repo asks about the very same subject
    res = core.check(store, repo="the geospatial repo", task="regex newline trap validation")
    # ASSERT (1) — it stays invisible. A word-match is not enough to cross the boundary.
    assert not res["rules"], "repo-scoped node must not leak into another repo's check"

    # ACT (2) — the owning repo asks the same question
    res2 = core.check(store, repo="dotnet-repo", task="regex newline trap validation")
    # ASSERT (2) — it is delivered. Isolation must not become suppression.
    assert res2["rules"], "owning repo should see its own repo-scoped rule"


def test_org_scope_visible_everywhere(store):
    """The other half of the boundary: org-scoped records reach every repo, including
    ones that did not exist when the record was written. That reach is the entire point
    of a shared layer — a lesson paid for once should protect the next project too."""
    # ARRANGE — prior art recorded org-wide (a fact about the world, not about one repo)
    core.record(store, type="PriorArt", title="Evangelista 2018 the study basin", scope="org",
                status="live", body="THREAT: refutes novelty claim")

    # ACT — a repo the record has never heard of asks a related question
    res = core.check(store, repo="any-new-repo", task="the target species change mapping the study basin")

    # ASSERT — it arrives, routed to the prior-art bucket so it reads as a warning
    assert res["threat_prior_art"], "org-scope prior art should reach every repo"


def test_staleness_demotes_not_deletes(store):
    """An expired record is marked stale, never removed.

    Deleting it would destroy the record that it was once true, and with it the ability
    to ask "when did we stop believing this, and why?". Demotion keeps the history and
    still stops a reader from trusting it blindly.
    """
    # ARRANGE — a record with a 1-day TTL, last verified at epoch 0 (1970), so far past due
    old = Node(type="Rule", title="license present", scope="org", ttl_days=1,
               verified_at=0)
    nid = store.add_node(old)

    # ACT — read it back
    n = store.get_node(nid)

    # ASSERT (1) — it is still there. Expiry demotes; it does not delete.
    assert n is not None, "an expired record must survive, not vanish"
    # ASSERT (2) — and it reports itself as stale so a briefing can flag it
    assert n.is_stale() is True


def test_recurrence_metric(store):
    """The metric the whole system is scored on: a defect class that came back even
    though a gate existed to catch it.

    It is deliberately an outcome measure, not an activity measure. "How many rules did
    we record" always goes up and flatters the system; "did the same mistake happen
    again" is the only number that can embarrass it.
    """
    # ARRANGE — a known defect and the gate that catches it
    d = core.record(store, type="Defect", title="class_path wrong", scope="org")
    g = core.record(store, type="Gate", title="classpath gate", scope="org")
    core.link(store, g, "CATCHES", d)

    # ASSERT (1) — baseline: a gate existing is not itself a recurrence
    assert store.recurrence_after_arming() == [], "no recurrence has happened yet"

    # ACT — the defect recurs in a repo that never armed that gate (RECURS_IN edge)
    repo_node = core.record(store, type="Entity", title="dotnet-repo", scope="repo:dotnet-repo",
                            repo="dotnet-repo")
    core.link(store, repo_node, "RECURS_IN", d)
    rows = store.recurrence_after_arming()

    # ASSERT (2) — exactly one recurrence is reported...
    assert len(rows) == 1
    # ASSERT (3) — ...and it names the gate that would have prevented it, which is the
    # actionable part: the fix is arming that gate here, not inventing something new.
    assert rows[0]["gate"] == "classpath gate"


def test_seed_file_loads(store, tmp_path, monkeypatch):
    """A real bundled seed file loads and produces a working briefing.

    Seed files are how a brand-new repo starts with knowledge instead of an empty store.
    This test uses a genuine shipped file rather than a fixture, because a hand-written
    fixture would only prove the loader handles the shape the author imagined.
    """
    seed = Path(__file__).resolve().parents[1] / "seed" / "geospatial-defects.json"
    if not seed.exists():
        pytest.skip("seed file not present")
    # ARRANGE — replay the seed file's nodes and edges into the in-memory store.
    # We drive `core` directly rather than the Client, because the Client would go
    # looking for a config file and a real database on disk; here we only care that
    # the seed FORMAT loads and produces a usable briefing.
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
    # ACT — a brand-new repo, which has learned nothing itself, asks about the task
    # the seeded lesson covers
    res = core.check(store, repo="brand-new-repo", task="scaffold an rslearn OlmoEarth model config class_path")

    # ASSERT (1) — the seeded gate arms for it. This is the cross-repo promise in one
    # line: knowledge paid for elsewhere protects a repo on its first day.
    assert res["armed_gates"], "seeded gate should arm for a new repo"
    # ASSERT (2) — and it survives rendering, so the agent actually sees it
    md = core.render_check_for_agent(res)
    assert "class_path" in md.lower()


def test_service_check(tmp_path, monkeypatch):
    """The shared HTTP service behaves like the local store, including its errors.

    `importorskip` means this test is skipped rather than failed when the optional
    service extras are not installed — the core package has no required dependencies,
    so its test suite must stay runnable without them.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from okl.service import create_app

    # ARRANGE — a store with one gate/defect pair, served over HTTP. This is the shape
    # several repos share: they all talk to one service instead of holding their own copy.
    s = Store("sqlite:///:memory:")
    d = core.record(s, type="Defect", title="temporal decoder axes", scope="org", verified=True)
    g = core.record(s, type="Gate", title="laptop dry-run decoder shapes", scope="org", verified=True)
    core.link(s, g, "CATCHES", d)
    app = create_app(store=s)
    client = TestClient(app)   # drives the app in-process; no real network involved

    # ASSERT (1) — the service is up and reports its own health honestly
    assert client.get("/health").json()["ok"] is True

    # ACT / ASSERT (2) — a check over HTTP returns the same briefing shape as local mode.
    # Remote and local must not diverge, or a repo's behaviour would change when it
    # connects to the shared store.
    r = client.post("/check", json={"repo": "x", "task": "temporal segmentation decoder axes"})
    assert r.status_code == 200 and r.json()["armed_gates"]
    # validation errors are the caller's: 400 WITH the message, never a 500 (E2E finding —
    # an agent inventing tags got an opaque 500 and reported the service as down)
    bad = client.post("/record", json={"type": "Rule", "title": "t", "scope": "org", "tags": "ci,pinning"})
    assert bad.status_code == 400 and "vocabulary" in bad.json()["detail"]


# ---- new-feature tests: schema, router, drift, idempotent seed, coverage ----

def test_record_symptom_cause_fix_roundtrip(store):
    """Symptom, cause and fix are stored as separate fields, not prose.

    That separation is what lets a briefing say "when you see X, do Y" instead of
    printing a paragraph. A reader skims the symptom to decide whether the record
    applies to them at all, which prose cannot support.
    """
    # ARRANGE / ACT — record a defect with all three parts (cause lives in `body`)
    nid = core.record(store, type="Defect", title="price tamper", scope="org",
                      body="cause: trusts client price", symptom="DTO carries Price",
                      fix="compute server-side", verified=True)

    # ASSERT — the structure survives the round trip; symptom and fix stay addressable
    n = store.get_node(nid)
    assert n.symptom == "DTO carries Price"
    assert n.fix == "compute server-side"


def test_check_router_actions(store):
    """A matched record becomes an imperative instruction, not just context.

    The difference matters: given a wall of background, a model tends to acknowledge it
    and carry on. Given "FIX: do this specific thing", it acts. The router turns records
    into that ordered action list, and the renderer puts it FIRST in the briefing.
    """
    # ARRANGE — one defect carrying a fix, so the router has something imperative to emit
    core.record(store, type="Defect", title="price tamper", scope="org",
                body="trusts client price", symptom="DTO carries Price",
                fix="compute server-side", verified=True)

    # ACT — ask about a task the record covers
    res = core.check(store, repo="r", task="add endpoint that sets a price")

    # ASSERT (1) — it was routed as an action to apply, not merely listed as background
    kinds = {a["kind"] for a in res["next_actions"]}
    assert "apply_fix" in kinds
    # ASSERT (2) — and the rendered briefing leads with that action list, carrying the
    # concrete fix text through to what the model actually reads
    md = core.render_check_for_agent(res)
    assert "Do this" in md
    assert "compute server-side" in md


def test_drift_fires_when_source_changes(store, tmp_path):
    """Drift fires when the code a rule governs changes after the rule was verified.

    This is the difference between a rule that merely got old and one whose subject moved
    underneath it. The first is handled by a TTL clock; this is event-driven, and it is
    the stronger signal because it means someone must actually go and look.

    The test builds a throwaway git repo because drift asks git — not the filesystem —
    when the governed files last changed.
    """
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
    # ARRANGE — a rule that declares the file it governs, verified right now. `files`
    # is what enrols a record in drift detection; a record without it is watched by nothing.
    nid = core.record(store, type="Rule", title="orders rule", scope="org",
                      files="orders.py", verified=True)

    # ASSERT (1) — nothing has changed since verification, so there is no drift
    assert drift.detect_drift(store.all_nodes(), "r", str(rd)) == []

    # ACT — the governed file changes. The sleep is not decorative: git commit timestamps
    # have one-second resolution, so without it the new commit could share a timestamp
    # with the verification and the comparison would be ambiguous.
    time.sleep(1)
    src.write_text("x=2\n"); git("add","-A"); git("commit","-m","change")
    hits = drift.detect_drift(store.all_nodes(), "r", str(rd))

    # ASSERT (2) — drift fires, naming the record whose ground truth moved underneath it.
    # This is the difference between a rule that expired on a clock and one whose subject
    # actually changed: only the second means someone must go look.
    assert len(hits) == 1
    assert hits[0].node_id == nid


def test_seed_is_idempotent(store, tmp_path):
    """Loading the same seed file twice must not duplicate its records.

    Seeding is something people re-run — after editing a file, or in CI. If each run
    appended, the store would fill with near-identical records and every briefing would
    repeat itself. Stable ids derived from the file name plus each node's `key` make a
    second run overwrite the same rows instead.
    """
    # ARRANGE — a seed file with two records and one edge between them
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
    """Subject tags come from a closed vocabulary, checked at write time.

    Tags decide which records a repo sees, so a typo ("securty") would quietly file a
    record where nobody looks. Rejecting unknown tags at the door is what keeps the
    filter trustworthy — the alternative is free-text tags that drift into noise.
    """
    nid = core.record(store, type="Defect", title="judge crash", scope="org",
                      tags="eval-integrity,data-quality")
    assert store.get_node(nid).tags == "eval-integrity,data-quality"
    with pytest.raises(ValueError):
        core.record(store, type="Defect", title="x", scope="org", tags="not-a-real-tag")


def test_check_filters_org_nodes_by_declared_interests(store):
    """Interests filter org-wide records by subject, with two deliberate escape hatches.

    Scope answers "who may see this"; tags answer "what is this about". A Python service
    should not be briefed on React rules however well the words match. But the filter must
    never hide a repo's OWN records, and must never hide an untagged one — missing
    metadata is not a reason to withhold a warning. Both exemptions are asserted below.
    """
    # ARRANGE — four records covering every combination the filter must handle
    core.record(store, type="Defect", title="judge crash on eval run", scope="org",
                tags="eval-integrity", fix="lead with failure count")
    core.record(store, type="Defect", title="localStorage tokens on eval page", scope="org",
                tags="react,security")
    core.record(store, type="Rule", title="eval budget parity", scope="org")  # untagged
    core.record(store, type="Defect", title="local eval quirk", scope="repo:r",
                tags="react")  # own repo, off-interest tag
    # ACT — a repo that declares two interests asks a question touching all four
    res = core.check(store, repo="r", task="eval judge localStorage budget quirk",
                     interests=["eval-integrity", "python-rag"])
    titles = {d["title"] for d in res["relevant_defects"]} | {r["title"] for r in res["rules"]}
    assert "judge crash on eval run" in titles, "matching-tag org node must pass"
    assert "eval budget parity" in titles, "untagged org node must pass"
    assert "local eval quirk" in titles, "own repo-scoped node must pass regardless of tags"
    assert "localStorage tokens on eval page" not in titles, "off-interest org node must be dropped"
    # ACT / ASSERT — with no interests declared, nothing is filtered: a repo that has
    # not opted in gets everything rather than silently getting less.
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
    """Without git, the drift gate cannot work, and init must say so out loud.

    Drift compares governed files against commit history; with no history there is
    nothing to compare. Installing a CI workflow that silently checks nothing would be
    worse than installing none, so init warns and skips it.
    """
    import argparse

    from okl.cli import cmd_init
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(repo="nogit", service=None, interests=None)
    assert cmd_init(args) == 0
    out = capsys.readouterr().out
    assert "not a git repository" in out and "DISABLED" in out
    assert not (tmp_path / ".github").exists()


def test_verify_stamps_only_from_evidence(store):
    """A verification stamp requires evidence. No run, no stamp.

    A "verified" flag anyone can set is a step grading its own homework. Requiring an
    evidence string means every stamp records WHICH check was run, so a weak check is at
    least a visible artifact rather than an invisible belief.
    """
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
    """A seeded record with no stated origin must not inherit the seeding repo's name.

    Seed files carry knowledge from OTHER projects. Defaulting a missing `repo` to
    whoever ran the import would rewrite history — the record would claim to come from
    a repo that never learned it, corrupting provenance and any per-repo metric built
    on it. Unknown origin must stay unknown, loudly.
    """
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

def test_actions_format_fits_a_small_context_budget(store):
    """A subagent working in a few thousand tokens cannot afford the full briefing.
    The compact format must carry the imperative content at a fraction of the size,
    and --limit must actually cap it."""
    for i in range(12):
        core.record(store, type="Defect", title=f"defect {i} in the orders endpoint", scope="org",
                    body="cause: " + ("prose that would bloat a full briefing. " * 20),
                    symptom=f"symptom {i} appears in the orders endpoint",
                    fix=f"apply fix {i}")
    res = core.check(store, repo="r", task="orders endpoint defect symptom")
    full = core.render_check_for_agent(res)
    compact = core.render_actions_only(res, limit=3)

    assert len(compact) < len(full) / 5, "compact must be far smaller than the full briefing"
    assert compact.count("\n- ") == 3, "limit must cap the number of actions"
    # the imperative content survives the compression
    assert "apply fix 0" in compact and "when:" in compact
    # and none of the prose bulk does
    assert "prose that would bloat" not in compact


def test_empty_store_is_never_reported_as_a_clean_check(store):
    """Zero matches has two causes that must not sound alike: the store holds rules and
    none apply here, or the store is empty and the check proved nothing. Conflating them
    reports silence as safety."""
    # empty store
    empty = core.check(store, repo="r", task="anything at all")
    assert empty["store_records"] == 0
    assert "EMPTY" in core.render_actions_only(empty)
    assert "proves nothing" in core.render_actions_only(empty)
    assert "EMPTY" in core.render_check_for_agent(empty)

    # populated store, genuinely unrelated task
    core.record(store, type="Rule", title="a rule about database migrations", scope="org",
                symptom="editing an applied migration", fix="add a new migration")
    none_apply = core.check(store, repo="r", task="zzz totally unrelated query zzz")
    assert none_apply["match_count"] == 0
    assert none_apply["store_records"] == 1
    out = core.render_actions_only(none_apply)
    assert "no encoded rule applies" in out and "EMPTY" not in out


def test_check_fails_closed_when_repo_is_not_configured(tmp_path, monkeypatch, capsys):
    """An unconfigured directory must not get a clean check. Reading there would create
    an empty database and then report 'no rules apply' against it, forever."""
    import argparse

    from okl.cli import cmd_check
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKL_SERVICE_URL", raising=False)
    args = argparse.Namespace(task="add an endpoint", repo=None, format="agent", limit=None)
    assert cmd_check(args) == 2, "must fail closed, not report a clean check"
    assert "NOT CONFIGURED" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.db")), "must not create a store just to read from it"


def test_check_limit_threads_through_the_client(tmp_path, monkeypatch):
    """--limit has to reach core.check, not just trim the rendered output."""
    import argparse

    from okl.cli import cmd_check
    from okl.client import Client
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "t"}))
    c = Client()
    for i in range(10):
        c.record(type="Rule", title=f"rule {i} about widgets", scope="org",
                 symptom=f"widget {i}", fix=f"do {i}")
    wide = c.check("widgets", limit=10)
    narrow = c.check("widgets", limit=1)
    assert narrow["match_count"] <= wide["match_count"]
    args = argparse.Namespace(task="widgets", repo=None, format="actions", limit=2)
    assert cmd_check(args) == 0

