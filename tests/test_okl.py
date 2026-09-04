"""End-to-end tests for the knowledge layer.

Every test follows ARRANGE / ACT / ASSERT with a short story per phase, so a reader
can learn the contract being checked without opening the code under test. Where a test
guards a security boundary, an ordering rule, or a "silence is not safety" invariant,
the assertions are numbered and each says which failure it prevents.
"""
import importlib.util
import json
import os
from pathlib import Path
from urllib import request as _req

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


def test_service_token_gates_reads_as_well_as_writes(monkeypatch):
    """When OKL_TOKEN is set, every endpoint but /health requires it.

    Writes were gated from the start and reads were not, which is the natural-looking
    split and the wrong one: a deployed service handed anyone who found the URL a
    `GET /nodes` dump of the org's whole encoded body — its known defects, its retired
    identifiers, its architecture decisions. That is a map of where the org is weak.
    Found by deploying the service and curling it without a credential.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from okl.service import create_app

    # ARRANGE — a token-protected service holding one record worth not leaking
    monkeypatch.setenv("OKL_TOKEN", "s3cret")
    s = Store("sqlite:///:memory:")
    core.record(s, type="Defect", title="auth bypass in the admin path", scope="org")
    client = TestClient(create_app(store=s))
    auth = {"Authorization": "Bearer s3cret"}

    # ASSERT (1) — /health stays open on purpose. Schedulers and load balancers probe it
    # holding no credential, and a deploy that cannot be health-checked never goes live.
    # It returns a count and a backend name, never record content.
    health = client.get("/health")
    assert health.status_code == 200
    assert "auth bypass" not in health.text

    # ASSERT (2) — every content endpoint refuses an anonymous caller. /nodes is the one
    # that mattered most: it dumps everything in a single unauthenticated GET.
    assert client.get("/nodes").status_code == 401
    assert client.get("/metric/recurrence").status_code == 401
    assert client.post("/check", json={"repo": "x", "task": "auth"}).status_code == 401
    assert client.post("/search", json={"query": "auth"}).status_code == 401
    assert client.post("/record", json={"type": "Rule", "title": "x", "scope": "org"}).status_code == 401

    # ASSERT (3) — and the token opens all of them, so the gate is a credential check
    # rather than an outage
    assert client.get("/nodes", headers=auth).status_code == 200
    assert client.post("/check", json={"repo": "x", "task": "auth"}, headers=auth).status_code == 200
    assert client.post("/record", json={"type": "Rule", "title": "x", "scope": "org"},
                       headers=auth).status_code == 200


def test_saving_config_keeps_the_service_token_out_of_git(tmp_path, monkeypatch):
    """`.okl/` ignores itself, so `okl connect --token` cannot commit a shared secret.

    The code carried a comment saying ".okl/ is gitignored" and wrote nothing to make it
    so. `okl connect --token` puts the service bearer credential in cleartext in
    `.okl/config.json`, so the next `git add .` committed it — and a token in git history
    outlives any later fix. Found by running the documented connect flow in a real repo
    and asking git what it would stage.
    """
    from okl.client import save_config

    # ARRANGE / ACT — the documented flow: connect with a token
    monkeypatch.chdir(tmp_path)
    save_config({"repo": "r", "service_url": "https://okl.internal", "token": "s3cret"})

    # ASSERT (1) — the directory carries its own ignore file, so no edit to the repo's
    # root .gitignore is needed and a repo that has none is still covered
    ignore = tmp_path / ".okl" / ".gitignore"
    assert ignore.exists()
    assert ignore.read_text().splitlines()[-1] == "*"

    # ASSERT (2) — the secret really is on disk; the ignore file is the only thing
    # standing between it and a commit, which is why assertion (1) is not cosmetic
    assert "s3cret" in (tmp_path / ".okl" / "config.json").read_text()

    # ASSERT (3) — writing config again does not clobber an ignore file someone edited
    ignore.write_text("# hand-edited\n*\n")
    save_config({"repo": "r2"})
    assert "hand-edited" in ignore.read_text()


def test_asgi_entrypoint_resolves_to_a_real_app_without_importing_the_database(monkeypatch):
    """`okl.service:app` is a working ASGI app, and importing the module stays cheap.

    These two requirements pull against each other, which is how the bug got in. `app`
    was a module-level `None` that only `run()` reassigned, so `uvicorn okl.service:app`
    — the command in this module's own docstring, and the default form every platform
    uses — started fine, bound the port, passed a port-liveness check, and returned 500
    to every request. Building the app at import instead would connect to the database
    whenever anything imported the module, including the CLI and this test suite.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import okl.service as svc

    # ARRANGE — a database URL that would fail loudly if anything connected to it
    monkeypatch.setenv("OKL_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(svc, "_app", None)   # forget any app a previous test built

    # ASSERT (1) — importing does not build the app, so it does not touch storage
    assert svc._app is None

    # ACT — resolve the attribute the way an ASGI server does
    app = svc.app

    # ASSERT (2) — what comes back actually serves requests. `is not None` would have
    # passed against the old code the moment any earlier test called run().
    assert TestClient(app).get("/health").json()["ok"] is True

    # ASSERT (3) — a typo'd entrypoint still raises AttributeError rather than silently
    # resolving, so `uvicorn okl.service:aap` fails at startup instead of at request time
    with pytest.raises(AttributeError):
        getattr(svc, "nonexistent_attribute")  # noqa: B009 — the lookup IS the assertion


def test_token_also_takes_down_the_openapi_spec_and_docs_ui(monkeypatch):
    """Setting OKL_TOKEN removes /openapi.json, /docs and /redoc; without it they stay.

    These were missed when the data routes were closed, because they are the one part of
    the surface `_auth` cannot reach — FastAPI mounts them itself, so adding a dependency
    to every handler leaves them open. They do not leak records, but they publish the
    endpoint list, every schema and exactly which routes want a credential: the map you
    would draw before attacking the rest. Found by reading the store's own rule that
    OpenAPI specs are dev-only, then testing whether this service obeyed it.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from okl.service import create_app

    s = Store("sqlite:///:memory:")

    # ASSERT (1) — with a token, the spec routes are gone entirely (404, not 401: the
    # route does not exist, so there is nothing to probe or brute-force)
    monkeypatch.setenv("OKL_TOKEN", "s3cret")
    closed = TestClient(create_app(store=s))
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert closed.get(path).status_code == 404, f"{path} still served with a token set"

    # ASSERT (2) — the data routes still work with the credential, so removing the spec
    # did not remove the API
    assert closed.post("/check", json={"repo": "x", "task": "t"},
                       headers={"Authorization": "Bearer s3cret"}).status_code == 200

    # ASSERT (3) — with no token this is someone's laptop, and the interactive docs are
    # useful there. Taking them away unconditionally would be a worse tool for no gain.
    monkeypatch.delenv("OKL_TOKEN", raising=False)
    open_app = TestClient(create_app(store=s))
    assert open_app.get("/openapi.json").status_code == 200
    assert open_app.get("/docs").status_code == 200


def test_cli_check_fails_closed_when_the_service_refuses_it(tmp_path, monkeypatch, capsys):
    """A 401 is a REFUSED check, not a clean one: exit 2, no reassuring output.

    Fail-closed was implemented for the unreachable case only. An authorization failure
    took a different code path — `ValueError`, not `OKLUnreachable` — and fell through
    to an unhandled traceback with exit 0, which a hook reads as "no rules apply".
    Silence is never safety, whatever the reason for the silence.
    """
    from okl.cli import main

    # ARRANGE — a repo pointed at a service that will reject it. Nothing listens on this
    # port; the rejection is simulated at the client boundary below.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(
        json.dumps({"repo": "r", "service_url": "http://127.0.0.1:9"}))

    def refuse(self, task, repo=None, limit=None):
        raise ValueError("OKL service rejected the request (401): missing or bad bearer token")
    monkeypatch.setattr("okl.client.Client.check", refuse)

    # ACT
    code = main(["check", "--task", "add a refund endpoint"])
    out = capsys.readouterr()

    # ASSERT (1) — non-zero, so a hook or CI step blocks instead of proceeding
    assert code == 2
    # ASSERT (2) — nothing on stdout that could be mistaken for a clean briefing
    assert out.out.strip() == ""
    # ASSERT (3) — and the message names the credential, since that is the actual fix
    assert "REFUSED" in out.err and "401" in out.err


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



@pytest.mark.skipif(not os.environ.get("OKL_TEST_POSTGRES_URL"),
                    reason="set OKL_TEST_POSTGRES_URL to run against a real Postgres")
def test_postgres_matches_sqlite_ranking_on_a_real_server():
    """Both backends must rank the SAME record first for the same query.

    The interface contract (an identical `search()` signature) is the easy half. The
    quality contract is the one that broke before: Postgres ran an unranked substring
    match while SQLite ran BM25, so promoting a repo to the shared service silently gave
    it worse retrieval than it had on a laptop. Asserting SQL shape against a fake
    connection cannot catch that — only a real server can.

    Skipped unless OKL_TEST_POSTGRES_URL is set; docs/DEPLOY.md has a throwaway cluster
    in four commands.

    The test builds its table inside a temporary schema and drops it afterwards, so it
    never touches a `node` table that was already there. The first version opened with
    `DELETE FROM node` against whatever the URL pointed at, which would have destroyed
    the whole store of anyone who set the variable to their real service to "just check
    parity" — a test whose worst case is worse than the bug it guards against.
    """
    # ARRANGE — one corpus, loaded identically into both backends. The fourth record
    # deliberately mentions BOTH topics, so a backend that merely MATCHES (rather than
    # ranks) can still return the wrong record first.
    records = [
        ("Defect", "rate limiter counts in process across replicas",
         "in-memory limiter grants a fresh allowance per instance"),
        ("Rule", "pin every tool that gates CI",
         "an unpinned linter retro-fails a branch that changed nothing"),
        ("Rule", "tokens never go in localStorage",
         "web storage is readable by any script on the page"),
        ("Defect", "the linter version was not pinned in the rate limiter repo",
         "mentions both topics, so matching alone is not enough to pass"),
        ("Rule", "ownership predicate belongs in the WHERE clause",
         "a non-owner row must never leave the database"),
    ]
    url = os.environ["OKL_TEST_POSTGRES_URL"]
    schema = "okl_parity_test"
    # Create the scratch schema on a throwaway connection, then hand the Store a URL
    # whose search_path points at it. libpq passes `options` straight through, so the
    # Store's own CREATE TABLE lands in the scratch schema without the Store needing to
    # know anything about schemas — and any real `public.node` stays invisible to it.
    import psycopg
    with psycopg.connect(url, autocommit=True) as setup:
        setup.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        setup.execute(f"CREATE SCHEMA {schema}")
    sep = "&" if "?" in url else "?"
    pg = Store(f"{url}{sep}options=-csearch_path%3D{schema}")
    lite = Store("sqlite:///:memory:")
    try:
        for s_ in (pg, lite):
            for t, title, body in records:
                core.record(s_, type=t, title=title, scope="org", body=body)

        # ACT / ASSERT (1) — the same record leads on every query, on both backends
        for query in ["rate limiter replicas", "pin linter CI", "tokens localStorage",
                      "ownership WHERE clause"]:
            a, b = lite.search(query, limit=3), pg.search(query, limit=3)
            assert a and b, f"both backends must return something for {query!r}"
            assert a[0].title == b[0].title, (
                f"backends disagree on {query!r}: sqlite={a[0].title!r} postgres={b[0].title!r}")

        # ASSERT (2) — the GIN index exists. Without it the ranked query still returns
        # the right answer but degrades to a sequential scan as the store grows, which is
        # the kind of regression nobody notices until the store is large.
        with pg._impl.conn.cursor() as c:
            c.execute("select indexname from pg_indexes where tablename='node' "
                      f"and schemaname='{schema}'")
            assert "node_tsv_idx" in {r[0] for r in c.fetchall()}
    finally:
        # Leave the server as it was found, whether the assertions passed or not.
        pg.close()
        with psycopg.connect(url, autocommit=True) as teardown:
            teardown.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None,
                    reason="requires the mcp extra: pip install 'org-knowledge-layer[mcp]'")
def test_mcp_server_builds_and_its_tools_actually_run(tmp_path, monkeypatch):
    """Build the real MCP server and call every tool through it.

    This test exists because the server shipped for weeks without ever being run, and
    the first live invocation found three defects at once: the SDK renamed its server
    class in 2.x (so `pip install [mcp]` produced a server that could not start), an
    explicit `repo=None` from the tool layer defeated the client's `setdefault` (so every
    repo-scoped record failed), and validation errors surfaced as an opaque "Error
    executing tool" the agent could not act on.

    Testing the tool functions in isolation would have caught none of them.
    """
    import asyncio

    from okl.client import Client
    from okl.mcp_server import _build

    # ARRANGE — a configured repo holding one record, so search has something to find
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "mcpdemo"}))
    Client().record(type="Defect", title="price tampering via a client-supplied amount",
                    scope="org", symptom="a request body carries a price",
                    fix="compute it server-side")

    def unwrap(res):
        c = getattr(res, "content", None)
        if isinstance(c, list | tuple):
            c = c[0]
        return getattr(c, "text", str(c))

    async def exercise():
        mcp = _build()   # ASSERT (1) — constructs under whichever SDK major is installed
        names = {t.name for t in await mcp.list_tools()}
        assert {"okl_check", "okl_record", "okl_search"} <= names

        # ASSERT (2) — the read path returns a real briefing, compact form included
        out = unwrap(await mcp.call_tool("okl_check", {
            "task": "add an endpoint that accepts a price", "compact": True, "limit": 2}))
        assert "price" in out.lower()

        # ASSERT (3) — scope="repo" resolves to repo:<name>. The tool layer passes every
        # field explicitly, so repo arrives as None and setdefault cannot fill it.
        rec = unwrap(await mcp.call_tool("okl_record", {
            "type": "Rule", "title": "recorded through the MCP layer", "scope": "repo"}))
        assert rec.startswith("recorded "), rec

        # ASSERT (4) — a bad tag returns readable guidance naming the vocabulary, not an
        # exception. An agent that cannot read the complaint cannot fix its own call.
        bad = unwrap(await mcp.call_tool("okl_record", {
            "type": "Rule", "title": "x", "scope": "org", "tags": "not-a-real-tag"}))
        assert bad.startswith("NOT RECORDED")
        assert "vocabulary" in bad

        # ASSERT (5) — the search path returns matches
        assert "tampering" in unwrap(await mcp.call_tool(
            "okl_search", {"query": "price tampering", "limit": 2})).lower()

    asyncio.run(exercise())


def test_a_self_declared_proposal_pack_must_cite_every_record(tmp_path, monkeypatch):
    """A pack marked `_proposed_by` is refused unless every node carries a citation.

    The commands that generate these files tell the agent "no citation, no record". An
    instruction with no mechanical trigger is the surface nobody runs, and the reviewer
    checking by hand is exactly the step that gets skipped on a 40-record proposal. An
    uncited record is the worst thing this store can hold: a plausible sentence nobody
    can trace, injected into every future task and believed.
    """
    from okl.client import Client
    from okl.seed import seed_from_file

    # ARRANGE — a configured repo, and a proposal pack with one cited and one uncited node
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    client = Client()

    def pack(nodes):
        p = tmp_path / "proposed.json"
        p.write_text(json.dumps({"_proposed_by": "seed-from-docs", "nodes": nodes}))
        return str(p)

    cited = {"key": "a", "type": "Rule", "title": "money is computed server-side",
             "scope": "repo:r", "found_by": "docs/specs/checkout.md:118"}
    uncited = {"key": "b", "type": "Rule", "title": "always validate input", "scope": "repo:r"}

    # ACT / ASSERT (1) — the import is refused, and names the offender so it can be fixed
    with pytest.raises(ValueError) as e:
        seed_from_file(client, pack([cited, uncited]))
    assert "found_by" in str(e.value)
    assert "b" in str(e.value)

    # ASSERT (2) — refused means NOTHING landed, not "the good ones went in". A partial
    # import would leave the reviewer unable to tell which half they still have to check.
    assert client.search("money computed server-side") == []

    # ASSERT (3) — with every node cited, the same pack imports
    assert seed_from_file(client, pack([cited])) == 1
    assert client.search("money computed server-side")

    # ASSERT (4) — curated packs carry provenance in other ways and are untouched by
    # this rule; only a pack that declares itself agent-proposed opts into it
    p = tmp_path / "curated.json"
    p.write_text(json.dumps({"nodes": [
        {"key": "c", "type": "Rule", "title": "outbox pattern for write-then-publish",
         "scope": "org", "repo": None}]}))
    assert seed_from_file(client, str(p)) == 1


def test_symptom_and_fix_are_searchable(store):
    """A record is retrievable by the words in its symptom and fix, not only its title.

    `symptom` is the field every command, doc and diagram calls "what a reader matches
    against" — the observable that says this record applies to the task in hand. It was
    the one field the index could not see, so a record written the way the guidance says
    to write it (short title, the distinguishing words in symptom and fix) came back from
    `check` as "no encoded rule applies". Found by seeding a record seeded from a spec and
    watching a task quoting its symptom verbatim match nothing.
    """
    # ARRANGE — the distinguishing words appear ONLY in symptom and fix. The title is
    # deliberately generic, the way a real one often is.
    core.record(store, type="Rule", title="money handling", scope="org",
                symptom="a request DTO carrying a price or total field",
                fix="drop the field; compute it from the catalogue server-side")
    core.record(store, type="Rule", title="pagination", scope="org",
                symptom="an offset-based query over a large table",
                fix="use keyset pagination past a few thousand rows")

    # ASSERT (1) — a task quoting the symptom finds the record
    hits = store.search("request DTO carrying a price", limit=5)
    assert hits, "a record must be findable by its symptom"
    assert hits[0].title == "money handling"

    # ASSERT (2) — and by words that appear only in the fix
    assert [n.title for n in store.search("keyset pagination", limit=5)][:1] == ["pagination"]

    # ASSERT (3) — title still outranks the other fields, so adding them did not flatten
    # relevance: "pagination" in a title beats "pagination" inside another record's fix
    assert store.search("pagination", limit=5)[0].title == "pagination"

    # ASSERT (4) — and the whole point, end to end: a briefing surfaces it
    res = core.check(store, repo="any", task="add an endpoint that takes a price")
    assert any("money handling" in r["title"] for r in res["rules"])


def test_an_index_built_before_symptom_was_indexed_is_rebuilt(tmp_path):
    """A store created by an older version rebuilds its search index on open.

    FTS5 cannot ALTER a column in, so the table is dropped and rebuilt from `node`, which
    is the source of truth. Without this, existing users would get the fix in the code and
    none of it in their data — the worst kind of upgrade, because everything looks fixed.
    """
    # ARRANGE — hand-build the pre-fix index shape and a record whose only distinguishing
    # words live in symptom, exactly as the old code would have left it
    db = tmp_path / "old.db"
    s = Store(f"sqlite:///{db}")
    core.record(s, type="Rule", title="money handling", scope="org",
                symptom="a request DTO carrying a price or total field", fix="compute it server-side")
    conn = s._impl.conn
    conn.execute("DROP TABLE node_fts")
    conn.execute("CREATE VIRTUAL TABLE node_fts USING fts5(id UNINDEXED, title, body)")
    conn.execute("INSERT INTO node_fts(id,title,body) SELECT id, title, coalesce(body,'') FROM node")
    conn.commit()
    assert s.search("request DTO carrying a price", limit=5) == []   # the old, broken state
    s.close()

    # ACT — reopen with the current code
    s2 = Store(f"sqlite:///{db}")

    # ASSERT — the index was rebuilt from the existing rows, so old records become
    # findable without anyone re-recording them
    assert [n.title for n in s2.search("request DTO carrying a price", limit=5)] == ["money handling"]
    s2.close()


def test_duplicate_scoring_ranks_a_paraphrase_above_an_unrelated_record(store):
    """The same rule, worded as a second document would word it, scores above noise.

    This is the case doc mining creates: CLAUDE.md, an ADR and a spec all state one rule,
    an agent paraphrases each heading, and three records arrive with different titles and
    nearly identical symptoms. Comparing titles alone misses exactly those.
    """
    # ARRANGE — one stored rule, plus an unrelated one to compete with it
    core.record(store, type="Rule", title="Missing ownership scope check is an IDOR",
                scope="org", symptom="an endpoint fetches an entity by id with no owner predicate",
                fix="add the caller's id to the WHERE clause; return 404 on no match")
    core.record(store, type="Rule", title="Log rotation on ingest hosts", scope="org",
                symptom="disk fills on a long-running ingest host", fix="rotate daily, keep 7")

    paraphrase = {"title": "Queries must filter by the requesting user",
                  "symptom": "an endpoint fetches a row by id with no owner predicate",
                  "fix": "put the owner in the WHERE clause and 404 when nothing matches"}

    # ACT
    hits = core.find_duplicates(store, paraphrase, threshold=0.0)

    # ASSERT (1) — it finds the right record, not merely *a* record. Matching the wrong
    # one is worse than matching none: it sends a reviewer to compare against the wrong
    # thing, and they conclude there is no duplicate.
    assert hits, "a paraphrase of a stored rule must surface it"
    assert "IDOR" in hits[0][1].title

    # ASSERT (2) — and it outranks the unrelated record by a clear margin
    scores = {n.title: s for s, n in core.find_duplicates(store, paraphrase, threshold=0.0, limit=9)}
    assert len(scores) >= 1
    top = max(scores.values())
    others = [v for k, v in scores.items() if "IDOR" not in k]
    assert all(top > v for v in others), f"paraphrase must outrank unrelated records: {scores}"

    # ASSERT (3) — a record never matches itself, or every import would flag everything
    stored = [n for n in store.all_nodes() if "IDOR" in n.title][0]
    assert all(n.id != stored.id for _, n in core.find_duplicates(store, stored, threshold=0.0))


def test_dedup_never_drops_or_merges(tmp_path, monkeypatch, capsys):
    """A proposal pack that resembles existing records still imports, with a warning.

    The citation rule blocks because an uncited record is unambiguously wrong. Similarity
    is not: the measured score bands for true paraphrases and for distinct-but-related
    records overlap, so a blocking check here would refuse good imports. Report, and let
    a person rule on it.
    """
    from okl.client import Client
    from okl.seed import seed_from_file

    # ARRANGE — a store holding a rule, and a pack proposing a paraphrase of it
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    client = Client()
    client.record(type="Rule", title="Missing ownership scope check is an IDOR", scope="org",
                  symptom="an endpoint fetches an entity by id with no owner predicate",
                  fix="add the caller's id to the WHERE clause")
    pack = tmp_path / "proposed.json"
    pack.write_text(json.dumps({"_proposed_by": "seed-from-docs", "nodes": [
        {"key": "a", "type": "Rule", "scope": "repo:r",
         "title": "Queries must filter by the requesting user",
         "symptom": "an endpoint fetches a row by id with no owner predicate",
         "fix": "put the owner in the WHERE clause", "found_by": "docs/rules.md:12"}]}))

    # ACT
    n = seed_from_file(client, str(pack))

    # ASSERT (1) — it imported. A fuzzy signal must not silently discard a record.
    assert n == 1
    assert client.search("filter by the requesting user")

    # ASSERT (2) — and the reviewer was told, with both sides named so the comparison
    # can actually be made
    err = capsys.readouterr().err
    assert "resemble records already in the store" in err
    assert "IDOR" in err


def _backend_conformance(store, label):
    """The behavioural contract every backend owes, asserted identically for each.

    Shared rather than duplicated per backend on purpose: the defect this guards was two
    backends satisfying the same *signatures* while one ranked results and the other
    returned an unranked substring match. Separate test bodies drift apart exactly the way
    the implementations did. One body, run against both, cannot.
    """
    from okl.store import _Backend

    # ASSERT (1) — it satisfies the declared Protocol at all
    assert isinstance(store._impl, _Backend), f"{label}: backend does not satisfy _Backend"

    core.record(store, type="Rule", title="ownership predicate belongs in the WHERE clause",
                scope="org", symptom="a fetch by id with no owner column in the query",
                fix="add the caller id to the WHERE clause")
    core.record(store, type="Rule", title="pin every tool that gates CI", scope="org",
                symptom="an unpinned linter in a required check",
                fix="pin the exact version")
    core.record(store, type="Defect", title="unrelated cache warming behaviour", scope="org",
                symptom="a cold cache on deploy", fix="warm it")

    # ASSERT (2) — RANKED, not insertion order. The best match leads.
    top = store.search("ownership predicate WHERE clause", limit=3)
    assert top, f"{label}: search returned nothing for a matching query"
    assert "ownership predicate" in top[0].title, f"{label}: results are not ranked, got {top[0].title!r}"

    # ASSERT (3) — symptom and fix are matchable, not just title and body
    assert any("pin every tool" in n.title for n in store.search("unpinned linter", limit=5)), \
        f"{label}: symptom is not searchable"

    # ASSERT (4) — OR-permissive across terms. Postgres's websearch_to_tsquery ANDs by
    # default, which silently returns fewer results than SQLite for the same query.
    assert len(store.search("ownership unpinned", limit=5)) >= 2, \
        f"{label}: multi-term query is AND-ing, not OR-ing"

    # ASSERT (5) — filters are exact
    assert store.search("ownership", scope="repo:nope", limit=5) == []
    assert all(n.type == "Rule" for n in store.search("ownership", node_types=["Rule"], limit=5))

    # ASSERT (6) — limit is honoured
    assert len(store.search("ownership OR pin OR cache", limit=1)) <= 1

    # ASSERT (7) — upsert is idempotent AND keeps any derived index consistent with the
    # row. Re-writing a record with a changed symptom must change what finds it.
    # Distinctive single tokens, because search is OR-permissive: asserting the ABSENCE
    # of "first symptom wording" would fail on a record still containing "symptom" and
    # "wording". Only a term unique to the old version can prove the old row is gone.
    nid = core.record(store, type="Rule", title="idempotency probe", scope="org",
                      symptom="zebrafish")
    before = len(store.all_nodes())
    store.add_node(Node(id=nid, type="Rule", title="idempotency probe", scope="org",
                        symptom="narwhal"))
    assert len(store.all_nodes()) == before, f"{label}: upsert duplicated instead of replacing"
    assert store.search("narwhal", limit=3), f"{label}: index went stale on upsert"
    assert not store.search("zebrafish", limit=3), f"{label}: stale index row survived the upsert"


def test_sqlite_backend_conformance(store):
    """The SQLite backend meets the contract."""
    _backend_conformance(store, "sqlite")


@pytest.mark.skipif(not os.environ.get("OKL_TEST_POSTGRES_URL"),
                    reason="set OKL_TEST_POSTGRES_URL to run against a real Postgres")
def test_postgres_backend_conformance():
    """The Postgres backend meets the SAME contract, asserted by the same code."""
    import psycopg
    url = os.environ["OKL_TEST_POSTGRES_URL"]
    schema = "okl_conformance_test"
    with psycopg.connect(url, autocommit=True) as setup:
        setup.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        setup.execute(f"CREATE SCHEMA {schema}")
    sep = "&" if "?" in url else "?"
    pg = Store(f"{url}{sep}options=-csearch_path%3D{schema}")
    try:
        _backend_conformance(pg, "postgres")
    finally:
        pg.close()
        with psycopg.connect(url, autocommit=True) as teardown:
            teardown.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def test_a_shared_subject_keeps_an_off_stack_record_in_the_briefing(store):
    """Interest filtering is any-match: one shared tag is enough. Exclusive stack
    filtering was tried, measured, and reverted — do not reintroduce it without reading why.

    The idea was that a record naming a stack the repo has not declared should be dropped
    even if it shares a subject, so .NET canon would stop reaching a Python repo. It was
    implemented, and the A/B measured the result: it hid 35 of 172 org records, and the
    briefed arm reproduced the rate-limiter defect described by a rule it had dropped
    (ab-20260902-0538, REPORT.md §4d).

    The reason is what a stack tag means. It records where a lesson was FOUND, not where it
    APPLIES. "In-memory rate limiters weaken to N× the limit at N instances" carries
    `dotnet` because it came from a .NET codebase and is true of every runtime; so is the
    IDOR rule, and "exit 0 having written zero files". Filtering on provenance as if it
    were applicability discards most of what a shared store exists to carry.

    The original complaint is still valid — genuinely stack-specific rules do reach the
    wrong repo — and fixing it needs applicability recorded separately from provenance.
    """
    # ARRANGE — a portable lesson that happens to carry the stack it was found in, and a
    # purely subject-tagged one. Same words, so only the filter can separate them.
    core.record(store, type="Rule", title="in-memory rate limiters weaken across instances",
                scope="org", tags="dotnet,security", body="pattern discipline")
    core.record(store, type="Rule", title="rate limits belong on the expensive endpoints",
                scope="org", tags="security", body="pattern discipline")

    # ACT — a repo that wants `security` but does no .NET
    res = core.check(store, repo="okl", task="rate limiters pattern discipline",
                     interests=["python", "security"])
    titles = [r["title"] for r in res["rules"]]

    # ASSERT (1) — the portable lesson arrives despite its foreign stack tag. This is the
    # assertion the reverted change broke, and the one the eval caught.
    assert any("in-memory rate limiters" in t for t in titles), \
        f"a portable rule was hidden by its provenance tag: {titles}"

    # ASSERT (2) — and the purely subject-tagged rule still arrives
    assert any("expensive endpoints" in t for t in titles), titles

    # ASSERT (3) — declaring no interests still disables filtering entirely
    assert len(core.check(store, repo="x", task="rate limiters pattern discipline",
                          interests=None)["rules"]) == 2


def test_client_resolves_the_shared_layer_from_the_environment(tmp_path, monkeypatch):
    """OKL_SERVICE_URL and OKL_TOKEN work with no config file and no `okl connect`.

    The CI verifier okl ships to consumers used to run `okl connect --token`, which wrote
    the bearer token into .okl/config.json on the runner. That step was removed on the
    strength of reading the client and concluding it reads both variables from the
    environment — a claim nothing checked. If it were wrong, every consumer's CI would
    quietly verify against its local store instead of the shared layer and still pass,
    which is the silent-degradation failure this project exists to prevent.

    Found by the architecture reviewer on its first real run, flagging the removal as
    assert-from-memory.
    """
    from okl.client import Client

    # ARRANGE — an empty directory: no .okl/config.json anywhere, so the environment is
    # the only possible source for either value
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKL_SERVICE_URL", "https://okl.internal")
    monkeypatch.setenv("OKL_TOKEN", "s3cret")
    client = Client()

    # ASSERT (1) — the URL is picked up, so the client is in remote mode with no config
    assert client.configured is True
    assert client.mode == "remote"
    assert client._remote_url("/check") == "https://okl.internal/check"

    # ASSERT (2) — the token reaches the Authorization header. Both verbs, because the
    # token used to go on POSTs only and every GET 401-ed against a private deployment.
    for req in (_req.Request("https://okl.internal/check", data=b"{}"),
                _req.Request("https://okl.internal/nodes")):
        client._authorize(req)
        assert req.get_header("Authorization") == "Bearer s3cret"

    # ASSERT (3) — and a config-file token still works when the env var is absent, since
    # that is the laptop path `okl connect --token` writes
    monkeypatch.delenv("OKL_TOKEN", raising=False)
    from_config = Client(config={"service_url": "https://okl.internal", "token": "from-file"})
    req = _req.Request("https://okl.internal/nodes")
    from_config._authorize(req)
    assert req.get_header("Authorization") == "Bearer from-file"


def test_applies_to_excludes_where_tags_must_not(store):
    """`applies_to` is the only exclusive filter, and unset means everywhere.

    Two records can be tagged identically — both `dotnet` — while one is a universal truth
    about distributed state and the other is about one framework's pipeline. Tags cannot
    tell them apart, because a stack tag records where a lesson was FOUND. Filtering on
    that hid 35 of 172 records and caused a measured regression (REPORT.md §4d).

    `applies_to` is a judgment made when recording, which is why it is allowed to exclude.
    Its default of None is the safety property: a store that has never used the field
    behaves exactly as it did before, so introducing it cannot regress retrieval.
    """
    # ARRANGE — a portable lesson found in .NET, and a genuinely .NET-only one. Same tags
    # as far as any tag-based filter can see; same words, so ranking cannot separate them.
    core.record(store, type="Rule", title="rate limiters weaken across instances",
                scope="org", tags="security,dotnet", body="pipeline discipline")
    core.record(store, type="Rule", title="wolverine pipeline order is load-bearing",
                scope="org", tags="dotnet,messaging", body="pipeline discipline",
                applies_to="dotnet")
    q = "rate limiters wolverine pipeline discipline"
    titles = lambda res: [r["title"] for r in res["rules"]]  # noqa: E731

    # ASSERT (1) — the portable lesson reaches a repo that does no .NET. This is the
    # assertion the reverted stack filter broke, and the one the A/B caught.
    py = titles(core.check(store, repo="okl", task=q, interests=["python", "security", "messaging"]))
    assert any("rate limiters" in t for t in py), py

    # ASSERT (2) — the framework-specific one does not
    assert not any("wolverine" in t for t in py), py

    # ASSERT (3) — but it does reach a repo that declares that stack
    dn = titles(core.check(store, repo="svc", task=q, interests=["dotnet", "messaging"]))
    assert any("wolverine" in t for t in dn), dn

    # ASSERT (4) — THE SAFETY PROPERTY: with no interests declared nothing is excluded,
    # so a repo that has not opted into filtering is unaffected by any curation.
    assert len(titles(core.check(store, repo="any", task=q, interests=None))) == 2

    # ASSERT (5) — the two filters compose and do not override each other. An explicit
    # `applies_to="any"` says "valid everywhere"; it does NOT force a record past the tag
    # filter, because tags answer a different question ("is this repo interested in the
    # subject"). A record must satisfy both, and the first draft of this test conflated
    # them — asserting a dotnet-only-tagged record should reach a python-only repo.
    core.record(store, type="Rule", title="explicitly portable pipeline lesson", scope="org",
                tags="dotnet,security", body="pipeline discipline", applies_to="any")
    shared = titles(core.check(store, repo="okl", task=q, interests=["python", "security"]))
    assert any("explicitly portable" in t for t in shared), shared
    # and with no shared subject, the tag filter still excludes it
    assert not any("explicitly portable" in t
                   for t in titles(core.check(store, repo="okl", task=q, interests=["python"])))


def test_applies_to_rejects_a_value_that_is_not_a_stack(store):
    """applies_to names stacks, not subjects — a typo must fail loudly at write time.

    `applies_to="security"` would read as sensible and silently exclude the record from
    every repo, since no repo declares a *stack* called security. A closed vocabulary
    checked at write time is the difference between a typo and a record nobody ever sees.
    """
    with pytest.raises(ValueError) as e:
        core.record(store, type="Rule", title="t", scope="org", applies_to="security")
    assert "applies_to must name stacks" in str(e.value)


def test_tags_are_searchable_but_never_outrank_content(store):
    """A tag can raise an on-subject record; it must not let a bare label beat real content.

    Tags were curated, validated, and invisible to retrieval: the index covered title, body,
    symptom and fix, so a tag could get a record EXCLUDED by the interest filter and never
    help it be FOUND. A task saying "run a security review" surfaced 2 of 12 security-tagged
    records; the same store with tags indexed surfaces 6.

    The weight is the whole risk. Tags is a one-or-two-word field and BM25 normalises by
    length, so an unweighted tag column would let a bare label outrank a record whose title
    and body are actually about the subject. It ships at 1.0 against title's 8.0 — additive,
    never dominant. Additive is also why this is safe in a way REPORT §4d was not: ranking
    can promote the wrong record, but it cannot hide a load-bearing one.
    """
    # ARRANGE — two records. One is ABOUT messaging in its content; the other merely
    # carries the tag and is about something else entirely.
    content = core.record(store, type="Rule", scope="org",
                          title="Messaging transport retries are idempotent",
                          body="Every messaging consumer must tolerate redelivery.",
                          symptom="a duplicate message applies an effect twice")
    tagged = core.record(store, type="Rule", scope="org", tags="messaging",
                         title="Prefer keyset pagination for deep offsets",
                         symptom="deep OFFSET scans get slower as the table grows")

    hits = [n.id for n in store.search("messaging", limit=10)]

    # ASSERT (1) — the tag made the second record findable at all. This is the whole point:
    # before indexing, nothing in its text mentioned messaging and it was unreachable.
    assert tagged in hits, "a tagged record must be findable by its subject"

    # ASSERT (2) — and it did NOT overtake the record that is genuinely about the subject.
    # If this flips, the weight is too high and a bare label is beating real content.
    assert hits.index(content) < hits.index(tagged), (
        "a tag match must not outrank a record whose title and body are about the subject")

    # ASSERT (3) — the weight itself, bounded from BOTH sides. The two assertions above
    # cannot do this: FTS5 MATCH finds by presence and bm25 weights only ORDER, so setting
    # the tags weight to 0.0 leaves the record findable and both assertions green while the
    # feature is silently off. Verified by setting it to 0.0 and watching them pass.
    src = (Path(__file__).resolve().parents[1] / "src" / "okl" / "store.py").read_text()
    weights = [float(w) for w in
               src.split("ORDER BY bm25(node_fts, ")[1].split(")")[0].split(", ")]
    _id_w, title_w, _body_w, _symptom_w, fix_w, tags_w = weights
    assert tags_w > 0, "a zero weight indexes tags and then ignores them when ranking"
    assert tags_w <= fix_w, "tags is a two-word field; weight it below the prose fields"
    assert tags_w * 4 <= title_w, "a tag must stay well under a title match"


def test_postgres_tsvector_covers_tags_and_migrates_its_index():
    """Backend parity: whatever SQLite indexes, the Postgres tsvector indexes too.

    The two backends satisfied the same signature while ranking differently once before —
    SQLite ran BM25 and Postgres ran an unranked substring match, so promoting a store to
    Postgres silently degraded every result. Signature parity is not quality parity, so
    each field added to one index gets asserted in the other.
    """
    from okl.store import _PG_TSV

    # ASSERT (1) — tags are in the vector, at D: the lowest weight Postgres offers, which
    # is the tsvector counterpart of the 1.0 the FTS5 path gives the same column.
    assert "tags" in _PG_TSV, "tags must be in the Postgres tsvector, as in FTS5"
    assert "'D'" in _PG_TSV, "tags belong at the lowest weight, not alongside title"
    # commas are separators, not tokens — same normalisation as the FTS5 insert
    assert "replace(coalesce(tags,''), ',', ' ')" in _PG_TSV

    # ASSERT (2) — the GIN index migration checks EVERY field the vector covers. A
    # condition naming one column goes stale the next time the vector grows, and the
    # failure is silent: the index survives, Postgres stops using it, and every search
    # quietly becomes a sequential scan.
    src = (Path(__file__).resolve().parents[1] / "src" / "okl" / "store.py").read_text()
    guard = src.split("indexname='node_tsv_idx'")[1].split("CREATE INDEX")[0]
    for col in ("symptom", "fix", "tags"):
        assert col in guard, f"index migration must notice {col} joining the tsvector"
