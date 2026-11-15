"""Graders by behaviour for evals/replay-tasks-457.json, the graded replay set grown for #457.

The same contract as tests/replay_graders_4bg.py, whose helpers this module repeats: each grader asks what the
stored lesson asks of the change, through what the code offers at the frozen commit (the CLI, a public
function, the shipped script or hook run as a process), never through a function, flag, field or message the
real fix invented, so any correct fix passes and no agent has to guess a name. Each has a positive control, so
a "fix" that simply refuses or does nothing fails too. t48 is a control: the frozen code already follows the
lesson, so it passes as it stands and fails only once that behaviour is taken out.

Copied into a room as tests/test_replay_grader.py, and run with the room as cwd and its src on PYTHONPATH.
Standard library, pytest and okl only; every helper a grader needs is in this file.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import okl

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(okl.__file__).resolve().parents[1]     # the code under test, for the children we start
_DROP = ("OKL_", "GIT_", "CLAUDE", "MCP_")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path_factory):
    """No store, service, token or briefing setting of the launching shell; a home of its own."""
    for name in [k for k in os.environ if k.startswith("OKL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("OKL_WARM", "0")
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)


def _env(**extra):
    """The environment for a child: this process's less okl's, git's and the session's variables, with
    this code first on PYTHONPATH, the warm model off and no briefing setting."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(_DROP)}
    env.update(PYTHONPATH=str(SRC), OKL_WARM="0")
    env.update(extra)
    return env


def _run(argv, cwd, env=None, **kw):
    """A child process, captured, with a time limit."""
    return subprocess.run(argv, cwd=cwd, env=env if env is not None else _env(), capture_output=True,
                          text=True, timeout=kw.pop("timeout", 300), **kw)


def _okl(cwd, *args, **env):
    """`python -m okl <args>` in `cwd`."""
    return _run([sys.executable, "-m", "okl", *args], cwd, _env(**env))


def _git(cwd, *args):
    """git in `cwd`, committing as a nobody, failing loudly."""
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c",
                           "commit.gpgsign=false", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env())


def _git_repo(path, files):
    """A git repository at `path` holding `files` ({relative path: text}), committed."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _configure(path, repo):
    """`path` as a repo named `repo` with a local store, as `okl init` would leave it."""
    (path / ".okl").mkdir(parents=True, exist_ok=True)
    (path / ".okl" / "config.json").write_text(json.dumps({"repo": repo}))
    return f"sqlite:///{path / '.okl' / 'okl.db'}"


def _ids(result):
    """Every lesson id a briefing holds, in any bucket."""
    return {item["id"] for items in result.values() if isinstance(items, list)
            for item in items if isinstance(item, dict) and item.get("id")}


def _load(name):
    """evals/<name>.py as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def _service(tmp_path, monkeypatch):
    """A repo connected to an okl service served in-process: the Client's real remote code (urllib,
    its encoding and error mapping) talks to the real app, with no socket."""
    from urllib.error import HTTPError
    from urllib.parse import urlsplit

    from fastapi.testclient import TestClient

    from okl.service import create_app
    from okl.store import Store

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "service_url": "http://okl.test"}))
    store = Store("sqlite:///:memory:")
    api = TestClient(create_app(store=store))

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
            raise HTTPError(req.full_url, r.status_code, r.reason_phrase, None, io.BytesIO(r.content))
        return Reply(r.content)

    monkeypatch.setattr("okl.client._req.urlopen", urlopen)
    return SimpleNamespace(store=store, api=api)


# ---- t19 · PR 30 · n_adea7f2c7373 ---------------------------------------------------------------

def _t19_install(tmp_path, folder):
    """This checkout's okl copied under `folder` (a name a checkout or an install path can have), with a
    seed/ beside it holding one pack that fits a python repo. Returns the folder's src and the pack."""
    import shutil
    home = tmp_path / folder
    shutil.copytree(SRC / "okl", home / "src" / "okl", ignore=shutil.ignore_patterns("__pycache__"))
    (home / "seed").mkdir()
    pack = home / "seed" / "python-pack.json"
    pack.write_text(json.dumps({"nodes": [
        {"key": "k1", "type": "Rule", "scope": "org", "title": "Close what you open", "tags": "python"}]}))
    return home / "src", pack


def _t19_seed_targets(text, cwd):
    """The path each suggested `okl seed <path>` line names, read as a shell would read the pasted line."""
    found = []
    for line in text.splitlines():
        if "okl seed " not in line:
            continue
        try:
            argv = shlex.split(line[line.index("okl seed "):])
        except ValueError as e:
            pytest.fail(f"a suggested command does not parse as shell: {line!r} ({e})")
        found.append((line, (Path(cwd) / argv[2]).resolve() if len(argv) > 2 else None))
    return found


# A space, a single quote, and a double quote: quoting the path in double quotes survives the first two
# but not the third (added after the alternatives check, where a double-quoting fix passed).
@pytest.mark.parametrize("folder", ["okl tools", "Joe's okl", 'the "okl" tools'])
@pytest.mark.parametrize("entry", ["init", "check"])
def test_t19_pr30(tmp_path, entry, folder):
    """The `okl seed <pack>` command okl suggests for an empty store, pasted into a shell, names the pack, when
    okl lives under a folder whose name holds a space, a single quote or a double quote: from `okl init` and
    from `okl check`'s advice. Control: the pack that fits the repo's interests is still suggested."""
    src, pack = _t19_install(tmp_path, folder)
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    env = _env(PYTHONPATH=str(src))
    if entry == "init":
        ran = _run([sys.executable, "-m", "okl", "init", "--repo", "r", "--interests", "python"], repo, env)
        text = ran.stdout
    else:
        _configure(repo, "r")
        cfg = json.loads((repo / ".okl" / "config.json").read_text())
        (repo / ".okl" / "config.json").write_text(json.dumps({**cfg, "interests": ["python"]}))
        ran = _run([sys.executable, "-m", "okl", "check", "--task", "add a cache"], repo, env)
        text = ran.stderr
    assert ran.returncode == 0, ran.stderr[-400:]

    targets = _t19_seed_targets(text, repo)

    assert targets, f"no `okl seed` command was suggested for the empty store:\n{text[-600:]}"
    for line, target in targets:
        assert target == pack.resolve(), f"pasted, {line.strip()!r} does not name {pack}"


# ---- t20 · PR 35 · seed:geospatial-enforcement-defects:d_invoked_by_nothing ---------------------

def _t20_report(where, request, catcher):
    """The recurrence report of a store holding a defect caught by a `catcher` record and one caught by a Gate,
    each recurred in another repo; read from a local store (core), or through the client over a service."""
    from okl import core
    from okl.store import Store
    if where == "service":
        store = request.getfixturevalue("_service").store
    else:
        store = Store("sqlite:///:memory:")
    soft = core.record(store, type=catcher, title="prove it with rollback tests", scope="org")
    loose = core.record(store, type="Defect", title="outbox stopped being atomic", scope="org")
    gate = core.record(store, type="Gate", title="ci rollback suite", scope="org")
    held = core.record(store, type="Defect", title="ledger lost a row", scope="org")
    core.link(store, soft, "CATCHES", loose)
    core.link(store, gate, "CATCHES", held)
    core.link(store, loose, "RECURS_IN", "svc")
    core.link(store, held, "RECURS_IN", "web")
    if where == "service":
        from okl.client import Client
        return Client().recurrence_report(), loose, held
    return core.recurrence_report(store), loose, held


@pytest.mark.parametrize("catcher", ["Rule", "Decision", "Claim"])
@pytest.mark.parametrize("where", ["local", "service"])
def test_t20_pr35(request, where, catcher):
    """okl metric's recurrence report counts a defect as armed only when a Gate catches it: a Rule, Decision or
    Claim that CATCHES it (a practice nothing runs) leaves it unarmed, its recurrence in the unarmed list, and
    it is not among the defects with a gate. Locally and over a service. Control: the defect a Gate catches is
    armed, its recurrence listed with the gate."""
    report, loose, held = _t20_report(where, request, catcher)

    armed = {r["defect_id"]: r for r in report["armed"]}
    unarmed = {r["defect_id"] for r in report["unarmed"]}
    assert held in armed and armed[held]["gates"] == ["ci rollback suite"], report
    assert loose not in armed, f"a {catcher} that catches a defect armed it: {armed.get(loose)}"
    assert loose in unarmed, report
    assert report["defects_with_gate"] == 1, report


# ---- t21 · PR 112 · n_e7988ff536fb --------------------------------------------------------------

@pytest.mark.parametrize("config", [
    "{not json",                 # a hand edit cut short
    "[1, 2]",                    # JSON, but not an object
    "null",
    b"\xff\xfe\x00junk",          # not text at all
    "a folder",                  # a directory where the file should be
    "unreadable",                # a file this user may not read
])
def test_t21_pr112(tmp_path, config):
    """`okl doctor` in a repo whose .okl/config.json is unreadable does not end in a traceback, and does not
    exit 1, which says it found something: nothing was found here. Control: with a readable config that turned
    CI off, doctor runs, exits 0 and says drift is not gated in CI."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    (repo / ".okl").mkdir()
    cfg = repo / ".okl" / "config.json"

    cfg.write_text(json.dumps({"repo": "r", "ci": False}))
    good = _okl(repo, "doctor")
    assert good.returncode == 0, (good.returncode, good.stdout[-300:], good.stderr[-300:])
    assert "not gated in CI" in good.stdout, good.stdout[-400:]

    if isinstance(config, bytes):
        cfg.write_bytes(config)
    elif config == "a folder":
        cfg.unlink()
        cfg.mkdir()
    elif config == "unreadable":
        cfg.chmod(0)
        if os.access(cfg, os.R_OK):
            pytest.skip("this user reads any file")
    else:
        cfg.write_text(config)
    ran = _okl(repo, "doctor")

    assert "Traceback" not in ran.stderr, ran.stderr[-400:]
    assert ran.returncode in (0, 2), (ran.returncode, ran.stdout[-300:], ran.stderr[-300:])


# ---- t22 · PR 135 · eval-scripts-no-exposure ----------------------------------------------------

def _t22_logged(url):
    """How many briefings the store at `url` has logged as exposure, for any repo."""
    from okl.store import Store
    store = Store(url)
    try:
        return len(store.briefings(None))
    finally:
        store.close()


def test_t22_pr135(tmp_path):
    """The layout pre-flight's briefings reach no agent, so running it against a store logs no exposure, while
    it still briefs every eval task and reports the layout lossless. Control: a real `okl check` against the
    same store is still logged as exposure."""
    from okl import core
    from okl.store import Store
    url = f"sqlite:///{tmp_path / 'store.db'}"
    store = Store(url)
    core.record(store, type="Rule", title="Hooks resolve the okl binary in layers", scope="org",
                body="a hook that calls okl must find it outside the dev shell", fix="try OKL_BIN, then PATH")
    store.close()
    tasks = (ROOT / "evals" / "tasks.jsonl").read_text().splitlines()
    env = _env(OKL_DATABASE_URL=url)
    env.pop("OKL_BRIEFING_LOG", None)

    ran = _run([sys.executable, str(ROOT / "evals" / "layout_preflight.py"), "--old-ref", "HEAD"], tmp_path, env)

    assert ran.returncode == 0 and "LAYOUT PRE-FLIGHT OK" in ran.stdout, (ran.stdout[-400:], ran.stderr[-400:])
    assert sum(" lost " in ln for ln in ran.stdout.splitlines()) == len(tasks), ran.stdout[-400:]
    assert _t22_logged(url) == 0, f"the pre-flight logged {_t22_logged(url)} briefings as exposure"
    real = _run([sys.executable, "-m", "okl", "check", "--task", "a hook that calls the okl binary"], tmp_path, env)
    assert real.returncode == 0, real.stderr[-300:]
    assert _t22_logged(url) == 1, "a real briefing was not logged as exposure"


# ---- t23 · PR 163 · guarantee-holds-on-every-write-path -----------------------------------------

def _t23_pack(path, status=None):
    """A seed pack of one lesson, `grid`, setting `status` when given; its id is seed:<file stem>:grid."""
    node = {"key": "grid", "type": "Rule", "scope": "org", "repo": "r", "title": f"Grid of {path.stem}"}
    if status:
        node["status"] = status
    path.write_text(json.dumps({"nodes": [node]}))
    return f"seed:{path.stem}:grid"


def _t23_seed(where, cwd, pack):
    """`okl seed <pack>`: as a process on a local store, or in-process over the service."""
    if where == "local":
        return _okl(cwd, "seed", str(pack)).returncode
    from okl.cli import main
    try:
        return main(["seed", str(pack)])
    except (Exception, SystemExit) as e:  # noqa: BLE001 - a refusal by any means is fine; the store is read after
        return repr(e)


def _t23_record(lesson, status):
    """The client's own record call, as an importer makes it (keep_verification), setting `status`."""
    from okl.client import Client
    try:
        return Client().record(id=lesson, type="Rule", scope="org", repo="r", title="Grid of site",
                               status=status, keep_verification=True)
    except Exception as e:  # noqa: BLE001 - a refusal by any means is fine; the store is read after
        return repr(e)


@pytest.mark.parametrize(("held", "status", "where", "how"), [
    (False, "obsolete", "local", "seed"), (False, "superseded", "local", "seed"),
    (True, "obsolete", "local", "seed"),            # the lesson is already held here, live
    (False, "obsolete", "service", "seed"), (True, "superseded", "service", "seed"),
    (False, "obsolete", "local", "client"), (True, "superseded", "service", "client"),
])
def test_t23_pr163(tmp_path, request, monkeypatch, held, status, where, how):  # noqa: PLR0917 - pytest passes these
    """Only `okl retire`, which logs a reason, retires a lesson: an import that sets a retired status on a new
    lesson, or on one held here live, never leaves it retired with no reason logged, whether it comes through
    `okl seed` or the client's record call, on a local store or over a service. Control: a pack with no status
    imports its lesson live, and a lesson retired here (with its reason) that its pack also calls retired is
    re-imported, still retired, its reason kept."""
    from okl import core
    from okl.store import Store
    if where == "service":
        store = request.getfixturevalue("_service").store
        cwd = tmp_path
    else:
        cwd = tmp_path / "repo"
        store = Store(_configure(cwd, "r"))
        monkeypatch.chdir(cwd)

    def state(lesson):
        n = store.get_node(lesson)
        return (n.status if n else "absent"), [r.reason for r in store.retirements(lesson)]

    try:
        pack = tmp_path / "site.json"
        if held:
            lesson = _t23_pack(pack)
            assert _t23_seed(where, cwd, pack) == 0
            assert state(lesson)[0] in (None, "", "live"), state(lesson)
        lesson = _t23_pack(pack, status)

        if how == "seed":
            _t23_seed(where, cwd, pack)
        else:
            _t23_record(lesson, status)

        got, reasons = state(lesson)
        assert got not in ("obsolete", "superseded", "retracted") or reasons, \
            f"the import left the lesson {got} with no reason logged"
        fresh = _t23_pack(tmp_path / "fresh.json")
        assert _t23_seed(where, cwd, tmp_path / "fresh.json") == 0
        assert state(fresh)[0] in (None, "", "live"), state(fresh)
        kept = _t23_pack(tmp_path / "kept.json")
        assert _t23_seed(where, cwd, tmp_path / "kept.json") == 0
        core.retire(store, kept, "the grid moved to the layout module", obsolete=True)
        _t23_pack(tmp_path / "kept.json", "obsolete")
        _t23_seed(where, cwd, tmp_path / "kept.json")
        assert state(kept) == ("obsolete", ["the grid moved to the layout module"]), state(kept)
    finally:
        if where == "local":
            store.close()


# ---- t24 · PR 266 · remote-path-test-through-client ---------------------------------------------

_T24_WORDS = ["logged out on refresh", "session lost"]


def _t24_write(how, given):
    """Write lesson `t1` with aliases `given` through the client, by `how`; returns what the store holds."""
    from okl.client import Client
    c = Client()
    if how == "seed":
        from okl.cli import main
        pack = Path.cwd() / "auth.json"
        pack.write_text(json.dumps({"nodes": [{"key": "t1", "type": "Rule", "scope": "org", "repo": "r",
                                               "title": "Refresh keeps the session", "aliases": given}]}))
        assert main(["seed", str(pack)]) == 0
        return "seed:auth:t1"
    if how == "record":
        return c.record(id="t1", type="Rule", title="Refresh keeps the session", scope="org", aliases=given)
    c.record(id="t1", type="Rule", title="Refresh keeps the session", scope="org")
    c.update("t1", aliases=given)
    return "t1"


@pytest.mark.parametrize("how", ["seed", "record", "update"])
@pytest.mark.parametrize("where", ["service", "local"])
def test_t24_pr266(request, tmp_path, monkeypatch, how, where):
    """Aliases given as a list (as a seed pack writes them) are stored, joined, through the real client over a
    service as they are on a local store: by `okl seed`, by Client.record and by Client.update. Control: the
    same on a local store, and aliases given as one string over the service."""
    if where == "service":
        store = request.getfixturevalue("_service").store
    else:
        monkeypatch.chdir(tmp_path)
        from okl.store import Store
        store = Store(_configure(tmp_path, "r"))
    try:
        try:
            lesson = _t24_write(how, list(_T24_WORDS))
        except Exception as e:  # noqa: BLE001 - whatever the client raises is the refusal this asserts is gone
            pytest.fail(f"{how} with a list of aliases was refused {where}: {e!r}")
        assert store.get_node(lesson).aliases == "; ".join(_T24_WORDS), store.get_node(lesson).aliases
        if where == "service" and how != "seed":
            from okl.client import Client
            Client().update(lesson, aliases="one phrase")
            assert store.get_node(lesson).aliases == "one phrase"
    finally:
        if where == "local":
            store.close()


# ---- t25 · PR 266 · n_e49be14d6207 --------------------------------------------------------------

@contextlib.contextmanager
def _t25_service():
    """A stand-in for a shared okl service on a loopback port: it notes every request and refuses each one."""
    import http.server
    import threading
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _note(self):
            seen.append(f"{self.command} {self.path}")
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _note   # noqa: N815 - http.server's names

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("named_by", ["variable", "config"])
def test_t25_pr266(tmp_path, named_by):
    """The seed comparison seeds throwaway stores whatever shared service this shell or directory names: run
    with OKL_SERVICE_URL set, or from a directory whose .okl/config.json names a service, it sends that service
    nothing, and still runs its comparison on its own throwaway stores (exit 0, its recall printed). Control: with
    no service named it runs and prints its comparison."""
    script = ROOT / "evals" / "compare_seed_briefings.py"
    plain = _run([sys.executable, str(script), "--against", "HEAD"], tmp_path, _env())
    assert plain.returncode == 0 and "held-out recall" in plain.stdout, (plain.stdout[-300:], plain.stderr[-600:])

    with _t25_service() as (url, seen):
        if named_by == "variable":
            env, cwd = _env(OKL_SERVICE_URL=url), tmp_path
        else:
            cwd = tmp_path / "connected"
            (cwd / ".okl").mkdir(parents=True)
            (cwd / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "service_url": url}))
            env = _env()
        ran = _run([sys.executable, str(script), "--against", "HEAD"], cwd, env)

    assert not seen, f"the comparison sent the shared service {len(seen)} request(s), first {seen[0]!r}"
    # Exit 0 and the comparison's own output, as the control asks: ending without a traceback does not show the
    # comparison ran (from code review on #477, after the alternatives check).
    assert ran.returncode == 0 and "held-out recall" in ran.stdout, \
        (named_by, ran.returncode, ran.stdout[-300:], "Traceback" in ran.stderr, ran.stderr[-600:])


# ---- t26 · PR 299 · filter-after-fetch-widens-window --------------------------------------------

def _t26_store(s, strong, weak):
    """Fill `s` with `strong` lessons naming the task's three subject words in their titles (the calibrated
    line's) and `weak` more carrying them only in their bodies (the floor's, ranked after them)."""
    from okl import core
    shown = [core.record(s, type="Rule", title=f"Ledger reconciliation across timezones, rule {i}", scope="org",
                         fix=f"reconcile the ledger nightly, batch {i}") for i in range(strong)]
    also = [core.record(s, type="Rule", title=f"Nightly batch job {i}", scope="org",
                        body="when the ledger reconciliation across timezones runs late, alert the on-call",
                        fix=f"page on-call for job {i}") for i in range(weak)]
    return set(shown), set(also)


def _t26_one_word_first():
    """A store whose search ranks every record sharing one subject word with the task ("ledger", in the
    title only) between the lessons the calibrated line shows and the ones that match in their bodies."""
    from okl.store import Store

    class Ranked(Store):
        def search(self, query, scope=None, node_types=None, limit=25):
            rows = super().search(query, scope, node_types, 500)
            rows.sort(key=lambda n: 0 if n.title.startswith("Ledger reconciliation")
                      else 2 if n.title.startswith("Nightly batch") else 1)
            return rows[:limit]
    return Ranked("sqlite:///:memory:")


# The last case was added after the alternatives check, where a fix that read the floor's whole window but
# never widened it for the lessons shown in full passed: at limit 1 the shown lesson and one-word matches
# fill that window, and the lessons that matched are ranked past it.
@pytest.mark.parametrize(("strong", "limit", "where"), [
    (3, 3, "local"), (4, 2, "local"), (5, 5, "local"), (3, 12, "local"), (3, 3, "service"),
    (1, 1, "one-word-first")])
def test_t26_pr299(request, strong, limit, where):
    """The tiered briefing's second tier names the other lessons that matched, up to the limit, whatever the
    lessons shown in full take from the top of the ranking: at a small limit whose shown lessons are the
    floor's first, it is not left empty; locally, through the client over a service, and when weaker one-word
    matches rank between the shown lesson and the others that matched. Control: at the default limit the
    same, no lesson is listed in both tiers, and a one-word match is never listed."""
    from okl import core
    from okl.store import Store
    if where == "service":
        s = request.getfixturevalue("_service").store
    elif where == "one-word-first":
        s = _t26_one_word_first()
        for i in range(8):
            core.record(s, type="Rule", title=f"Ledger export {i}", scope="org", fix=f"export batch {i}")
    else:
        s = Store("sqlite:///:memory:")
    strong_ids, weak_ids = _t26_store(s, strong, 6)
    task = "ledger reconciliation across timezones"
    try:
        if where == "service":
            from okl.client import Client
            res = Client().check(task, limit=limit)
        else:
            res = core.check(s, "r", task, limit=limit, decision="tiered")
    finally:
        if where != "service":
            s.close()

    shown = _ids({k: v for k, v in res.items() if k != "also_matched"})
    also = [e["id"] for e in res.get("also_matched") or []]
    assert shown, f"nothing was shown in full: {res}"
    assert not set(also) & shown, "a lesson shown in full was listed again in the second tier"
    assert set(also) <= strong_ids | weak_ids, f"a one-word match was listed in the second tier: {also}"
    assert len(also) == min(limit, len(strong_ids | weak_ids) - len(shown)), \
        f"limit {limit}: {len(shown)} shown, second tier {also} though {len(weak_ids)} more matched"


# ---- t27 · PR 299 · hook-cli-version-skew -------------------------------------------------------

def _t27_older(monkeypatch, refuse):
    """Put an older okl service in front of the in-process one: it validates `decision` as a service built
    before the tiered answer did (only floor or calibrated; anything else is pydantic's 422). With `refuse`
    it refuses every request with that status instead."""
    from urllib.error import HTTPError

    import okl.client
    newer = okl.client._req.urlopen

    def urlopen(req, timeout=None):
        body = json.loads(req.data) if req.data else {}
        if refuse:
            detail = {"detail": "missing or bad bearer token"} if refuse == 401 else {"detail": [{
                "type": "less_than_equal", "loc": ["body", "limit"], "msg": "Input should be less than or equal "
                "to 50", "input": body.get("limit"), "ctx": {"le": 50}}]}
            raise HTTPError(req.full_url, refuse, "refused", None, io.BytesIO(json.dumps(detail).encode()))
        if req.full_url.endswith("/check") and body.get("decision") not in (None, "floor", "calibrated"):
            detail = {"detail": [{"type": "literal_error", "loc": ["body", "decision"],
                                  "msg": "Input should be 'floor' or 'calibrated'", "input": body["decision"],
                                  "ctx": {"expected": "'floor' or 'calibrated'"}}]}
            raise HTTPError(req.full_url, 422, "Unprocessable Entity", None, io.BytesIO(json.dumps(detail).encode()))
        return newer(req, timeout=timeout)

    monkeypatch.setattr("okl.client._req.urlopen", urlopen)


@pytest.mark.parametrize("entry", ["client", "cli"])
def test_t27_pr299(_service, monkeypatch, capsys, entry):
    """A client whose default decision an older service does not know still gets a briefing from it, the
    lesson that matches included, rather than a refusal on every prompt: through Client.check and through
    `okl check`. Control: a refusal that is not about the decision (a 401, a 422 on another field) still
    refuses the check (exit 2)."""
    from okl import core
    from okl.cli import main
    from okl.client import Client
    core.record(_service.store, id="ledger-tz", type="Rule", title="Ledger reconciliation across timezones",
                scope="org", fix="reconcile in UTC, then convert for display")
    task = "ledger reconciliation across timezones"
    _t27_older(monkeypatch, refuse=None)

    if entry == "client":
        try:
            res = Client().check(task)
        except Exception as e:  # noqa: BLE001 - whatever the client raises is the refusal this asserts is gone
            pytest.fail(f"an older service's refusal of the decision failed the check: {e!r}")
        briefed = _ids(res) | {e.get("id") for e in res.get("also_matched") or []}
        assert "ledger-tz" in briefed, res
    else:
        code = main(["check", "--task", task])
        out = capsys.readouterr()
        assert code == 0, f"okl check against an older service exited {code}: {out.err[-400:]}"
        assert "Ledger reconciliation across timezones" in out.out, out.out[-600:]

    for status in (401, 422):
        _t27_older(monkeypatch, refuse=status)
        assert main(["check", "--task", task]) == 2, f"a {status} that is not about the decision was not a refusal"
        capsys.readouterr()


# ---- t28 · PR 387 · guarantee-holds-on-every-write-path -----------------------------------------

def _t28_write(where, store, **fields):
    """Record through core on `store`, or through the client (local, or over the service)."""
    from okl import core
    from okl.client import Client
    if where == "core":
        return core.record(store, **fields)
    return Client().record(**fields)


@pytest.mark.parametrize("where", ["core", "client", "service"])
def test_t28_pr387(request, tmp_path, monkeypatch, where):
    """A lesson is never replaced by itself, whichever path writes the replacement: a record whose old id
    (supersedes) is its own id is refused or leaves the lesson live, with no retirement logged, through core,
    the local client or the client over a service. Control: a record that supersedes another id still retires
    that one as replaced by it, and stays live itself."""
    from okl.store import Store
    if where == "service":
        store = request.getfixturevalue("_service").store
    else:
        monkeypatch.chdir(tmp_path)
        store = Store(_configure(tmp_path, "r"))
    lesson = {"type": "Rule", "title": "Grid snaps to eight", "scope": "org", "keep_verification": True}
    try:
        _t28_write(where, store, id="seed:layout:grid", **lesson)
        with contextlib.suppress(Exception):   # a refusal is a right answer; the store is read after
            _t28_write(where, store, id="seed:layout:grid", supersedes="seed:layout:grid", **lesson)
        n = store.get_node("seed:layout:grid")
        assert n is not None and n.status not in ("superseded", "obsolete", "retracted"), \
            f"the lesson was retired as replaced by itself ({n and n.status})"
        assert store.retirements("seed:layout:grid") == [], "a retirement was logged for a lesson replacing itself"

        _t28_write(where, store, id="seed:old-layout:gap", **{**lesson, "title": "Gap is a multiple of four"})
        _t28_write(where, store, id="seed:layout:gap", supersedes="seed:old-layout:gap",
                   **{**lesson, "title": "Gap is a multiple of four"})
        assert store.get_node("seed:old-layout:gap").status == "superseded"
        assert [r.by for r in store.retirements("seed:old-layout:gap")] == ["seed:layout:gap"]
        assert store.get_node("seed:layout:gap").status not in ("superseded", "obsolete", "retracted")
    finally:
        if where != "service":
            store.close()


# ---- t29 · PR 387 · report-commands-use-briefable-set -------------------------------------------

_T29_LESSON = ["--type", "Rule", "--scope", "org", "--title", "Every ledger read goes through the audit trail",
               "--symptom", "ledger entries returned without an audit row", "--fix",
               "call the audit trail before returning ledger entries"]


@pytest.mark.parametrize(("retired", "reported"), [
    (None, True),            # two live copies: a pair
    ("--by", False),         # one replaced by the other: briefed no more, settled
    ("--obsolete", False),   # one obsolete: briefed no more
    ("wrong", True),         # one retracted: still briefed, as AVOID, so a live repeat of it is a pair
])
def test_t29_pr387(tmp_path, retired, reported):
    """`okl dedup` compares the lessons a briefing can show: a pair where one is superseded by the other, or
    obsolete, is not reported (exit 0), while a live lesson repeating a retracted one still is (exit 1, both
    named). Control: two live copies are reported."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    _configure(repo, "r")
    for lesson in ("ledger-a", "ledger-b"):
        made = _okl(repo, "record", "--id", lesson, *_T29_LESSON)
        assert made.returncode == 0, made.stderr[-300:]
    if retired is not None:
        how = ["--by", "ledger-b"] if retired == "--by" else [] if retired == "wrong" else ["--obsolete"]
        gone = _okl(repo, "retire", "ledger-a", *how, "--reason", "the same lesson twice")
        assert gone.returncode == 0, gone.stderr[-300:]

    ran = _okl(repo, "dedup")

    named = "[ledger-a]" in ran.stdout and "[ledger-b]" in ran.stdout
    assert ran.returncode == (1 if reported else 0), (retired, ran.returncode, ran.stdout[-500:], ran.stderr[-300:])
    assert named is reported, (retired, ran.stdout[-500:])


# ---- t30 · PR 380 · n_e7988ff536fb --------------------------------------------------------------

@pytest.mark.parametrize("store", ["corrupt file", "postgres down"])
def test_t30_pr380(tmp_path, store):
    """`okl doctor` in a repo whose store cannot be read (a corrupt database file, a Postgres server that is
    down) does not end in a traceback, and does not exit 1, which says it found something. Control: with a
    readable store, doctor reports what the repo's interests hide and exits 0."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    assert _okl(repo, "init", "--repo", "r", "--no-claude", "--no-seed", "--no-ci", "--interests",
                "python").returncode == 0
    rec = _okl(repo, "record", "--type", "Rule", "--scope", "org", "--title", "A security lesson", "--body",
               "something to know", "--tags", "security")
    assert rec.returncode == 0, rec.stderr[-300:]
    good = _okl(repo, "doctor")
    assert good.returncode == 0 and "interests" in good.stdout, (good.returncode, good.stdout[-400:])

    env = {}
    if store == "corrupt file":
        (repo / ".okl" / "okl.db").write_bytes(b"not a database " * 100)
    else:
        if importlib.util.find_spec("psycopg") is None:
            pytest.skip("psycopg, okl's Postgres extra, is not installed")
        env = {"OKL_DATABASE_URL": "postgresql://okl@127.0.0.1:9/okl?connect_timeout=3"}
    ran = _okl(repo, "doctor", **env)

    assert "Traceback" not in ran.stderr, ran.stderr[-600:]
    assert ran.returncode in (0, 2), (ran.returncode, ran.stdout[-300:], ran.stderr[-300:])


# ---- t31 · PR 256 · n_aa3e45a2ecd6 --------------------------------------------------------------

# Two of the probe's own tasks, each citing the lesson that governs it.
_T31_TASKS = {"idor_endpoint": "t31-order-owner", "price_tamper": "t31-catalogue-price"}
_T31_TEXT = {"t31-order-owner": ("Scope an order lookup to the user who owns it",
                                 "an endpoint returns any user's order by its id"),
             "t31-catalogue-price": ("Price an order from the catalogue, never from the request",
                                     "an order total is computed from the price the client sent")}


def _t31_room(tmp_path, absent):
    """A repo whose evals/tasks.jsonl lists the two tasks, and whose store holds every lesson they cite
    except `absent`."""
    from okl import core
    from okl.store import Store
    room = tmp_path / "room"
    url = _configure(room, "r")
    (room / "evals").mkdir()
    (room / "evals" / "tasks.jsonl").write_text("".join(
        json.dumps({"id": tid, "defect_node": nid, "signal": "s",
                    "task": f"Add an HTTP endpoint for orders: {_T31_TEXT[nid][1]}"}) + "\n"
        for tid, nid in _T31_TASKS.items()))
    s = Store(url)
    for nid, (title, symptom) in _T31_TEXT.items():
        if nid != absent:
            core.record(s, id=nid, type="Defect", scope="org", title=title, symptom=symptom,
                        fix="read it from the server's own records")
    s.close()
    return room


@pytest.mark.parametrize("absent", [None, *_T31_TASKS.values()])
def test_t31_pr256(tmp_path, absent):
    """The rephrasing probe reads which lesson governs each eval task from evals/tasks.jsonl. A task whose
    lesson the store does not hold is refused before any recall row is printed (a non-zero exit naming the
    lesson, not a traceback), whether it is the first task or a later one: a missing lesson must never read
    as a vocabulary miss. Control: with every lesson present the probe runs and prints each task's rows."""
    room = _t31_room(tmp_path, absent)

    ran = _run([sys.executable, str(ROOT / "evals" / "probe_rephrase.py")], room)

    rows = [ln for ln in ran.stdout.splitlines() if ln.split(" ", 1)[0] in _T31_TASKS]
    if absent is None:
        assert ran.returncode == 0, ran.stderr[-400:]
        assert {ln.split()[0] for ln in rows} == set(_T31_TASKS), ran.stdout[-600:]
        return
    assert "Traceback" not in ran.stderr, f"a missing lesson crashed the probe: {ran.stderr[-300:]}"
    assert ran.returncode != 0, "the probe ran although a task's governing lesson is not in the store"
    assert absent in ran.stdout + ran.stderr, (ran.stdout[-300:], ran.stderr[-300:])
    assert not rows, f"recall rows were printed before the missing lesson was refused: {rows[:2]}"


# ---- t32 · PR 267 · n_b578addf6269 --------------------------------------------------------------

# A stand-in embedding model (words hashed into 64 dimensions, unit length, model2vec's encode
# shape), so the semantic arm can run with no download; and a launcher that runs a script with the
# model available, missing, or available while the store has no vectors.
_T32_MODEL = '''
import hashlib, math, re


class _T32Model:
    def encode(self, texts, normalize=True):
        out = []
        for text in texts:
            v = [0.0] * 64
            for w in re.findall(r"[a-z0-9]+", text.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out
'''
_T32_LAUNCH = _T32_MODEL + '''
import runpy, sys
from okl import semantic


def _missing(*a, **k):
    raise semantic.SemanticUnavailableError("the model is not cached on this machine")


semantic.load_model = _missing if sys.argv[1] == "no-model" else (lambda *a, **k: _T32Model())
script = sys.argv[2]
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
'''
_T32_LESSONS = {"t32-token": ("Keep the access token in memory", "an access token written to web storage"),
                "t32-cursor": ("Paginate with a cursor", "an offset query over a large table"),
                "t32-price": ("Price an order from the catalogue", "an order total from the client's price")}


def _t32_room(tmp_path, monkeypatch, vectors):
    """A repo holding the grid's inputs (two tasks, their held-out wordings, two chat prompts) and a store of
    three lessons, embedded by the stand-in model when `vectors`."""
    from okl import core, semantic
    from okl.store import Store
    room = tmp_path / "room"
    url = _configure(room, "okl")
    (room / "evals").mkdir()
    tasks = [{"id": "spa_tokens", "defect_node": "t32-token", "task": "keep the access token across a page reload"},
             {"id": "react_fetch", "defect_node": "t32-cursor", "task": "page through a large table of orders"}]
    (room / "evals" / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (room / "evals" / "heldout_variants.json").write_text(json.dumps({
        t["id"]: {label: t["task"] + f" ({label})" for label in ("ticket", "paraphrase", "bug-report")}
        for t in tasks}))
    (room / "evals" / "probe_prompts.json").write_text(json.dumps(
        {"prompts": ["the order price in the request", "access token after a reload"]}))
    s = Store(url)
    for nid, (title, symptom) in _T32_LESSONS.items():
        core.record(s, id=nid, type="Rule", scope="org", title=title, symptom=symptom, fix="do it the safe way")
    if vectors:
        source = tmp_path / "t32_model.py"
        source.write_text(_T32_MODEL)
        spec = importlib.util.spec_from_file_location("t32_model", source)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        monkeypatch.setattr(semantic, "load_model", lambda *a, **k: model._T32Model())
        semantic.build_index(s)
    s.close()
    return room


@pytest.mark.parametrize("arm", ["runs", "no-model", "no-vectors"])
def test_t32_pr267(tmp_path, monkeypatch, arm):
    """The grid that picks the semantic arm's line measures that arm, so a cell it fills while the arm
    fell back to full-text (the model missing, or the store holding no vectors) must not print as a
    measurement: the grid stops (a non-zero exit, no traceback) before printing a hybrid row. Control: when
    the arm runs, the grid prints its eight cells and exits 0."""
    room = _t32_room(tmp_path, monkeypatch, vectors=arm != "no-vectors")

    ran = _run([sys.executable, "-c", _T32_LAUNCH, "no-model" if arm == "no-model" else "model",
                str(ROOT / "evals" / "hybrid_grid.py")], room)

    cells = [ln for ln in ran.stdout.splitlines() if re.match(r"^0\.\d\d\s+(rrf|linear)\b", ln)]
    if arm == "runs":
        assert ran.returncode == 0, ran.stderr[-400:]
        assert len(cells) == 8, ran.stdout[-600:]
        return
    assert "Traceback" not in ran.stderr, ran.stderr[-300:]
    assert not cells, f"a fallen-back full-text cell printed as a semantic measurement: {cells[:2]}"
    assert ran.returncode != 0, "the grid finished although the semantic arm never ran"


# ---- t33 · PR 275 · n_b578addf6269 --------------------------------------------------------------

# A stand-in embedding model (words hashed into 64 dimensions, unit length, model2vec's encode
# shape), so the semantic arm can run with no download; and a launcher that runs a script with the
# model available or missing, and a reranker that keeps the order it is given.
_T33_MODEL = '''
import hashlib, math, re


class _T33Model:
    def encode(self, texts, normalize=True):
        out = []
        for text in texts:
            v = [0.0] * 64
            for w in re.findall(r"[a-z0-9]+", text.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out
'''
_T33_LAUNCH = _T33_MODEL + '''
import runpy, sys
from okl import rerank, semantic


def _missing(*a, **k):
    raise semantic.SemanticUnavailableError("the model is not cached on this machine")


semantic.load_model = _missing if sys.argv[1] == "no-model" else (lambda *a, **k: _T33Model())
rerank.rerank = lambda task, nodes, *a, **k: (list(nodes), {n.id: 0.0 for n in nodes})
script = sys.argv[2]
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
'''


def _t33_room(tmp_path, monkeypatch, vectors):
    """A repo holding the admission grid's inputs (two tasks, the probe whose variants it reads, two chat
    prompts) and a store of three lessons, embedded by the stand-in model when `vectors`."""
    from okl import core, semantic
    from okl.store import Store
    room = tmp_path / "room"
    url = _configure(room, "okl")
    (room / "evals").mkdir()
    tasks = [{"id": "spa_tokens", "defect_node": "t33-token", "task": "keep the access token across a page reload"},
             {"id": "react_fetch", "defect_node": "t33-cursor", "task": "page through a large table of orders"}]
    (room / "evals" / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (room / "evals" / "probe_rephrase.py").write_text((ROOT / "evals" / "probe_rephrase.py").read_text())
    (room / "evals" / "probe_prompts.json").write_text(json.dumps(
        {"prompts": ["the order price in the request", "access token after a reload"]}))
    s = Store(url)
    for nid, title, symptom in (("t33-token", "Keep the access token in memory", "an access token written to web storage"),
                                ("t33-cursor", "Paginate with a cursor", "an offset query over a large table"),
                                ("t33-price", "Price an order from the catalogue", "an order total from the client's price")):
        core.record(s, id=nid, type="Rule", scope="org", title=title, symptom=symptom, fix="do it the safe way")
    if vectors:
        source = tmp_path / "t33_model.py"
        source.write_text(_T33_MODEL)
        spec = importlib.util.spec_from_file_location("t33_model", source)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        monkeypatch.setattr(semantic, "load_model", lambda *a, **k: model._T33Model())
        semantic.build_index(s)
    s.close()
    return room


@pytest.mark.parametrize("arm", ["runs", "no-model", "no-vectors"])
def test_t33_pr275(tmp_path, monkeypatch, arm):
    """The admission grid reads each candidate's cosine from the semantic arm and its rank from the
    reranker. When the semantic arm fell back to full-text (no model, or no vectors), its cosine grid holds
    no cosines, so the grid must stop (a non-zero exit, no traceback) before printing it. The reranker is a
    stand-in that keeps the order, so only the semantic arm is in question. Control: when the arm runs, the
    grid prints and exits 0."""
    room = _t33_room(tmp_path, monkeypatch, vectors=arm != "no-vectors")

    ran = _run([sys.executable, "-c", _T33_LAUNCH, "no-model" if arm == "no-model" else "model",
                str(ROOT / "evals" / "admission_grid.py")], room)

    if arm == "runs":
        assert ran.returncode == 0, ran.stderr[-400:]
        assert "GRID" in ran.stdout, ran.stdout[-600:]
        return
    assert "Traceback" not in ran.stderr, ran.stderr[-300:]
    assert "GRID" not in ran.stdout, "a cosine grid was printed although the semantic arm never ran"
    assert ran.returncode != 0, "the grid finished although the semantic arm never ran"


# ---- t34 · PR 269 · doc-init-flags --------------------------------------------------------------

@pytest.mark.parametrize(("doc", "flag"), [
    ("Start with `okl init --repo my-repo --no-claude` in the repo.", None),       # real flags, in a command
    ("Pass `--no-seed` to okl init to start with an empty store.", None),          # a real flag, on its own
    ("Start with `okl init --repo my-repo --no-c` in the repo.", "--no-c"),       # the start of two flags
    ("Pass `--no` to okl init to skip the extras.", "--no"),                       # the start of four
])
def test_t34_pr269(tmp_path, doc, flag):
    """The check behind doc-init-flags fails on an `okl init` flag the README or guide documents that the CLI
    does not have, also when the documented text is the start of real flags' names, in a command or on its
    own; `okl init` itself refuses each of those (exit 2). Control: docs naming only real flags pass."""
    (tmp_path / "ci").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "ci" / "check-init-flags.py").write_text((ROOT / "ci" / "check-init-flags.py").read_text())
    (tmp_path / "README.md").write_text(f"# r\n\n{doc}\n")
    (tmp_path / "docs" / "GETTING-STARTED.md").write_text(
        "# Guide\n\nRun `okl init --repo my-repo --dry-run` first to see what it writes.\n")

    ran = _run([sys.executable, str(tmp_path / "ci" / "check-init-flags.py")], tmp_path)

    assert "Traceback" not in ran.stderr, ran.stderr[-400:]
    if flag is None:
        assert ran.returncode == 0, (ran.stdout[-300:], ran.stderr[-300:])
        return
    assert _okl(tmp_path, "init", flag).returncode == 2       # the documented flag does not work
    assert ran.returncode == 1, f"the check passed a documented flag `okl init` refuses: {flag}"
    assert flag in ran.stdout + ran.stderr, ran.stderr[-300:]


# ---- t35 · PR 308 · n_e49be14d6207 --------------------------------------------------------------

def _t35_bench():
    """evals/bench/run.py as a module."""
    spec = importlib.util.spec_from_file_location("t35_bench_run", ROOT / "evals" / "bench" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _t35_service():
    """A local HTTP service that answers 503 to everything and keeps the path of each request."""
    import http.server
    import threading
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _any(self):
            seen.append(self.path)
            self.send_response(503)
            self.end_headers()
        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any   # noqa: N815 - http.server's names

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


@pytest.mark.parametrize("named", [None, "OKL_DATABASE_URL", "OKL_SERVICE_URL"])
def test_t35_pr308(tmp_path, monkeypatch, named):
    """The bench builds its corpus (every seed pack) in a throwaway store of its own. A store or service
    named in the environment must not receive it: a real store keeps exactly what it held, and a service
    receives no request. Control: the corpus is built, in the directory the bench names, either way."""
    from okl import core
    from okl.store import Store
    real = tmp_path / "real" / "okl.db"
    real.parent.mkdir()
    s = Store(f"sqlite:///{real}")
    core.record(s, id="t35-real", type="Rule", scope="org", title="a lesson the real store holds")
    s.close()
    server, seen = _t35_service()
    if named == "OKL_DATABASE_URL":
        monkeypatch.setenv(named, f"sqlite:///{real}")
    elif named == "OKL_SERVICE_URL":
        monkeypatch.setenv(named, f"http://127.0.0.1:{server.server_address[1]}")
    for proxy in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(proxy, raising=False)
    bench = _t35_bench()
    raised, ids = None, set()
    try:
        corpus = bench.build_corpus(tmp_path / "corpus")
        try:
            ids = {n.id for n in corpus.all_nodes()}
        finally:
            corpus.close()
    except Exception as e:  # noqa: BLE001 - reported below, after what the service saw
        raised = e
    finally:
        server.shutdown()
        server.server_close()

    assert not seen, f"building the corpus sent {len(seen)} request(s) to the service the environment named"
    s = Store(f"sqlite:///{real}")
    held = {n.id for n in s.all_nodes()}
    s.close()
    assert held == {"t35-real"}, f"the corpus was seeded into the store the environment named ({len(held)} records)"
    if raised is not None:
        pytest.fail(f"build_corpus raised with {named} set: {type(raised).__name__}: {raised}")
    assert len(ids) > 100 and "t35-real" not in ids, len(ids)
    assert (tmp_path / "corpus").is_dir() and any((tmp_path / "corpus").rglob("*.db"))


# ---- t36 · PR 309 · n_967ef9825472 --------------------------------------------------------------

_T36_WORDS = ("migration", "catalogue", "pagination")


# "written" was added after the alternatives check, where a fix that committed the rebuild only on success but
# never rolled the failed one back passed: the store that failed to rebuild was only closed, which discards
# the pending drop, while a write through it commits that drop.
@pytest.mark.parametrize("after", ["closed", "written"])
@pytest.mark.parametrize("then", ["unicode61", "porter unicode61"])
def test_t36_pr309(tmp_path, monkeypatch, then, after):
    """The full-text index is derived from the node table and rebuilt on open when its tokenizer setting
    changes. A rebuild that fails part-way (here the setting names a tokenizer this SQLite lacks) must not
    leave a store whose index looks current but is empty, whether the store that failed is closed at once or
    first takes a write: the next open, under the old setting or a valid new one, still finds every lesson.
    Control: the lessons are found before the failure, and the store opens and searches normally after it."""
    from okl import core
    from okl import store as okl_store
    from okl.store import Store
    url = f"sqlite:///{tmp_path / 'okl.db'}"
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "unicode61")
    s = Store(url)
    ids = {core.record(s, type="Rule", scope="org", title=f"{w} handling", body=f"the {w} rule") for w in _T36_WORDS}
    assert {n.id for w in _T36_WORDS for n in s.search(w, limit=10)} == ids
    s.close()

    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", "t36_no_such_tokenizer")
    try:
        failed = Store(url)
    except Exception:  # noqa: BLE001 - refusing to open is a right answer too
        failed = None
    if failed is not None:
        try:
            if after == "written":
                with contextlib.suppress(Exception):   # refusing the write is a right answer too
                    core.record(failed, type="Rule", scope="org", title="rollback handling", body="the rollback rule")
        finally:
            failed.close()
    monkeypatch.setattr(okl_store, "FTS_TOKENIZE", then)
    try:
        s = Store(url)
        try:
            found = {n.id for w in _T36_WORDS for n in s.search(w, limit=10)}
        finally:
            s.close()
    except Exception as e:  # noqa: BLE001 - the store must open again once the setting is valid
        pytest.fail(f"the store did not open under {then!r} after the failed rebuild: {type(e).__name__}: {e}")

    assert found == ids, f"after a failed rebuild, search under {then!r} finds {len(found)} of {len(ids)} lessons"


# ---- t37 · PR 312 · model-reply-parse-fails-open-loudly -----------------------------------------

def _t37_replies(yes, other):
    """(reply, the verdict to read from it): prose with braces before the verdict, a reply quoting the
    format first, stray braces after it, two verdicts (the last stands), and replies that hold none."""
    return [
        (json.dumps({"verdict": yes, "reason": "r"}), yes),
        ("The diff changes `parse({x})` in one place.\n" + json.dumps({"verdict": yes, "reason": "r"}), yes),
        ('The answer format is {"verdict": "a|b", "reason": "..."}.\nMine:\n'
         + json.dumps({"verdict": other, "reason": "r"}), other),
        ("```json\n" + json.dumps({"verdict": other, "reason": "r"}) + "\n```\nSee {the note} above.", other),
        (json.dumps({"verdict": yes, "reason": "first"}) + "\nOn reflection:\n"
         + json.dumps({"verdict": other, "reason": "second"}), other),
        ("I could not decide {at all}.", None),
        (json.dumps({"verdict": "t37-not-a-verdict", "reason": "r"}), None),
    ]


@pytest.mark.parametrize("script", ["drift_mutate", "lesson_census"])
def test_t37_pr312(script):
    """The judges' replies are read for their verdict wherever it is: after prose holding braces, after a
    quoted answer format, before stray braces; with two, the last stands. Both scripts that read one (the
    mutation run's and the census's) do so. Control: a bare verdict is read, and a reply with no valid
    verdict reads as none."""
    mod = _load(script)
    if script == "drift_mutate":
        read, yes, other = mod.judged, "broken", "intact"
    else:
        yes, other = list(mod.VERDICTS)[:2]

        def read(reply):
            got = mod.parse_verdict(reply)
            return got.get("verdict") if got else None
    wrong = [(reply[:60], want, read(reply)) for reply, want in _t37_replies(yes, other) if read(reply) != want]
    assert not wrong, f"{script}: verdicts misread (reply, wanted, read): {wrong}"


# ---- t38 · PR 326 · n_713b8c104f12 --------------------------------------------------------------

def _t38_count(units, lists):
    """drift_widen_cost.count's shape, with nothing counted: the git walk is not what is tested."""
    return {"units": len(units), "per_lesson": {lid: dict.fromkeys(lists, 0) for lid in lists["before"]},
            "touched": dict.fromkeys(lists, 0), "lesson_rechecks": dict.fromkeys(lists, 0)}


@pytest.mark.parametrize("after", ["HEAD", "t38-no-such-revision", "mian"])
def test_t38_pr326(monkeypatch, capsys, after):
    """`drift_widen_cost.py --after <rev>` compares each lesson's governed files before and after. A revision
    that names no commit must be refused (a non-zero exit and no receipt), never read as a snapshot with
    no lessons, which reports every lesson's files as cleared. Control: a real commit with a snapshot runs
    and writes its receipt."""
    dwc = _load("drift_widen_cost")
    monkeypatch.setattr(dwc, "count", _t38_count)
    monkeypatch.setattr(sys, "argv", ["drift_widen_cost.py", "--after", after])
    results = ROOT / "evals" / "results"
    before = set(results.glob("drift-widen-cost-*.json"))
    try:
        code = dwc.main()
    except SystemExit as e:
        code = e.code
    finally:
        written = set(results.glob("drift-widen-cost-*.json")) - before
        for f in written:
            f.unlink()
    out = capsys.readouterr()
    if after == "HEAD":
        assert code in (0, None), out.err[-300:]
        assert written, "the control run wrote no receipt"
        return
    assert code not in (0, None), f"--after {after!r} ran as a snapshot with no lessons: {out.out[-300:]}"
    assert not written, "a receipt was written for a revision that names no commit"


# ---- t39 · PR 267 · n_e49be14d6207 --------------------------------------------------------------

def _t39_service():
    """A local HTTP service that answers 503 to everything and keeps the path of each request."""
    import http.server
    import threading
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _any(self):
            seen.append(self.path)
            self.send_response(503)
            self.end_headers()
        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any   # noqa: N815 - http.server's names

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


@pytest.mark.parametrize("named", [None, "environment", "checkout config"])
def test_t39_pr267(tmp_path, named):
    """The pipeline diagram is traced from a throwaway store seeded from the checkout's seed packs. A service
    named for the checkout, in the environment or in the checkout's own .okl/config.json, must not receive
    those seeds: the service sees no request and the trace still runs on the seeded corpus. The script is run
    from a copy of the checkout holding the committed packs. Control: with no service named, it prints the
    traced counts."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "seed").mkdir()
    (repo / "docs" / "render_pipeline_diagram.py").write_text((ROOT / "docs" / "render_pipeline_diagram.py").read_text())
    for pack in sorted((ROOT / "seed").glob("*.json")):
        (repo / "seed" / pack.name).write_text(pack.read_text())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    server, seen = _t39_service()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    if named == "checkout config":
        (repo / ".okl").mkdir()
        (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "okl", "service_url": url}))
    env = _env(OKL_SERVICE_URL=url) if named == "environment" else _env()
    for proxy in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        env.pop(proxy, None)
    try:
        ran = _run([sys.executable, str(repo / "docs" / "render_pipeline_diagram.py"), "--json"], elsewhere, env)
    finally:
        server.shutdown()
        server.server_close()

    assert not seen, f"seeding the trace's store sent {len(seen)} request(s) to the service named in the {named}"
    assert ran.returncode == 0, ran.stderr[-400:]
    assert json.loads(ran.stdout)["corpus"] > 100, ran.stdout[-300:]


# ---- t40 · PR 50 · n_d8166465591e --------------------------------------------------------------

def _t40_snapshot(root):
    """Every file under `root` with its bytes, to see whether any was created or changed."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _t40_repo(tmp_path):
    """A git repository with a .claude/ directory, as a cloned repo that uses Claude Code would be."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n", ".claude/README": "the team's notes\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    return repo, outside


@pytest.mark.parametrize("link", ["stop-hook", "prompt-hook", "settings", "claude-dir", "mcp", "workflow",
                                  "uninstall-settings"])
def test_t40_pr50(tmp_path, link):
    """okl init writes only real files inside the repo: a symlink the repo holds where okl writes (dangling or
    not: a hook, settings.json, .mcp.json, the CI workflow, or the .claude/ directory itself), and `okl init
    --uninstall` meeting a symlinked settings.json, create or change no file outside the repo, with no
    traceback. Control: in a repo without links, init still installs both hooks, registers them in
    .claude/settings.json and writes the workflow."""
    clean, _ = _t40_repo(tmp_path / "clean")
    made = _okl(clean, "init", "--repo", "r")
    assert made.returncode == 0, made.stderr[-400:]
    hooks = clean / ".claude" / "hooks"
    assert (hooks / "userpromptsubmit-okl-check.sh").is_file(), "init no longer installs the prompt hook"
    assert (hooks / "stop-okl-encode.sh").is_file(), "init no longer installs the Stop hook"
    registered = (clean / ".claude" / "settings.json").read_text()
    assert "userpromptsubmit-okl-check.sh" in registered and "stop-okl-encode.sh" in registered, registered
    assert (clean / ".github" / "workflows" / "okl-verify.yml").is_file(), "init no longer writes the workflow"

    repo, outside = _t40_repo(tmp_path / "linked")
    target = outside / "target"
    if link in ("stop-hook", "prompt-hook"):
        name = "stop-okl-encode.sh" if link == "stop-hook" else "userpromptsubmit-okl-check.sh"
        (repo / ".claude" / "hooks").mkdir()
        (repo / ".claude" / "hooks" / name).symlink_to(target)          # dangling: points at nothing yet
    elif link in ("settings", "uninstall-settings"):
        target.write_text(registered if link == "uninstall-settings" else '{"theirs": true}\n')
        (repo / ".claude" / "settings.json").symlink_to(target)
    elif link == "claude-dir":
        target.mkdir()
        (repo / ".claude" / "README").unlink()
        (repo / ".claude").rmdir()
        (repo / ".claude").symlink_to(target, target_is_directory=True)
    elif link == "mcp":
        target.write_text('{"mcpServers": {"theirs": {"command": "x"}}}\n')
        (repo / ".mcp.json").symlink_to(target)
    else:
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "okl-verify.yml").symlink_to(target)
    before = _t40_snapshot(outside)

    ran = _okl(repo, "init", "--uninstall") if link == "uninstall-settings" else _okl(repo, "init", "--repo", "r")

    assert "Traceback" not in ran.stderr, ran.stderr[-600:]
    assert _t40_snapshot(outside) == before, f"okl wrote outside the repo through the {link} symlink"


# ---- t41 · PR 373 · fail-closed-at-every-entry-point -------------------------------------------

# Start the service one documented way in a fresh process, and say what an unauthenticated caller then
# gets. argv: "asgi" (what `uvicorn okl.service:app` does: import the module, read its `app`), or
# "serve <host>" (`okl serve --host <host>` with uvicorn's run replaced by a stand-in that keeps the app
# instead of binding a port); then an optional token to try as a bearer.
_T41_PROBE = (
    "import importlib, json, sys\n"
    "from fastapi.testclient import TestClient\n"
    "mode, rest = sys.argv[1], sys.argv[2:]\n"
    "app, rc = None, None\n"
    "try:\n"
    "    if mode == 'serve':\n"
    "        import uvicorn\n"
    "        kept = {}\n"
    "        uvicorn.run = lambda app, **kw: kept.update(app=app)\n"
    "        from okl.cli import main\n"
    "        rc = main(['serve', '--host', rest.pop(0), '--port', '8099'])\n"
    "        app = kept.get('app')\n"
    "    else:\n"
    "        app = getattr(importlib.import_module('okl.service'), 'app')\n"
    "except BaseException as e:\n"
    "    print(json.dumps({'built': False, 'rc': rc, 'error': repr(e)[:300]}))\n"
    "    sys.exit(0)\n"
    "if app is None:\n"
    "    print(json.dumps({'built': False, 'rc': rc}))\n"
    "    sys.exit(0)\n"
    "api = TestClient(app)\n"
    "bare = api.get('/nodes').status_code\n"
    "auth = api.get('/nodes', headers={'Authorization': 'Bearer ' + rest[0]}).status_code if rest else None\n"
    "print(json.dumps({'built': True, 'rc': rc, 'bare': bare, 'auth': auth}))\n"
)


def _t41_start(tmp_path, argv, **env):
    """Run the probe with a throwaway store; its verdict."""
    ran = _run([sys.executable, "-c", _T41_PROBE, *argv], tmp_path,
               _env(OKL_DATABASE_URL=f"sqlite:///{tmp_path / 'svc.db'}", **env), timeout=120)
    assert ran.returncode == 0 and ran.stdout.strip(), ran.stderr[-600:]
    return json.loads(ran.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("start", ["asgi-no-token", "asgi-empty-token", "serve-open-host", "asgi-token",
                                   "serve-loopback"])
def test_t41_pr373(tmp_path, start):
    """With no OKL_TOKEN (unset, or set but empty), no documented way of starting the service serves the store
    to an unauthenticated caller: `uvicorn okl.service:app` (the entry point the deploy guide gives) either
    refuses to build or answers GET /nodes with an error, as `okl serve` off loopback already refuses. Control:
    with a token the ASGI entry point still serves, to the bearer only; `okl serve --host 127.0.0.1` with no
    token still serves on the laptop."""
    if start in ("asgi-no-token", "asgi-empty-token"):
        got = _t41_start(tmp_path, ["asgi"], **({"OKL_TOKEN": ""} if start == "asgi-empty-token" else {}))
        assert not (got["built"] and got["bare"] == 200), f"{start}: the ASGI entry point served the store open: {got}"
    elif start == "serve-open-host":
        got = _t41_start(tmp_path, ["serve", "0.0.0.0"])
        assert not got["built"] and got["rc"] == 2, f"okl serve on 0.0.0.0 with no token: {got}"
    elif start == "asgi-token":
        token = f"t41-{os.getpid()}"
        got = _t41_start(tmp_path, ["asgi", token], OKL_TOKEN=token)
        assert got["built"] and got["auth"] == 200 and got["bare"] != 200, f"with a token: {got}"
    else:
        got = _t41_start(tmp_path, ["serve", "127.0.0.1"])
        assert got["built"] and got["bare"] == 200 and got["rc"] in (0, None), f"local okl serve: {got}"


# ---- t42 · PR 300 · model-server-warm-up-before-serving ----------------------------------------

# The warm server with a stand-in for the model: loading is instant, the first inference takes 1.5 s (the
# runtime allocating its working memory, longer than a prompt waits) and every later one is immediate.
# No model is loaded or downloaded.
_T42_SERVER = (
    "import sys, time\n"
    "from okl import warm\n"
    "calls = []\n"
    "def load_model():\n"
    "    def encode(texts, kind):\n"
    "        calls.append(kind)\n"
    "        if len(calls) == 1:\n"
    "            time.sleep(1.5)\n"
    "        return [[1.0] + [0.0] * (warm.DIM - 1) for _ in texts]\n"
    "    return encode\n"
    "warm.load_model = load_model\n"
    "sys.exit(warm.serve())\n"
)


def test_t42_pr300(monkeypatch, tmp_path):
    """Once a freshly started warm server answers at all, the first prompt's vector arrives within the time
    a prompt waits for it, and quickly, though the model's first inference is slow: that cost is paid before
    the server serves, not by a prompt. Control: the vectors are the model's, and a second prompt is
    answered too."""
    import shutil
    import tempfile
    import time

    from okl import warm
    room = tempfile.mkdtemp(prefix="okl-t42-", dir="/tmp")     # a short path: a Unix socket's is limited
    sock = f"{room}/w.sock"
    monkeypatch.setenv("OKL_WARM_SOCKET", sock)
    log = tmp_path / "server.log"
    with log.open("w") as out:
        proc = subprocess.Popen([sys.executable, "-c", _T42_SERVER], env=_env(OKL_WARM_SOCKET=sock),
                                stdout=out, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 30
        while warm.ping() is None:
            assert proc.poll() is None, f"the server exited: {log.read_text()[-400:]}"
            assert time.monotonic() < deadline, "the server never answered"
            time.sleep(0.05)
        asked = time.monotonic()
        try:
            first = warm.embed(["add pagination to the orders list"], "query")
        except warm.WarmUnavailableError as e:
            pytest.fail(f"the first prompt after a start was briefed without the model: {e}")
        waited = time.monotonic() - asked
        assert waited < 1.0, f"the first prompt waited {waited:.1f} s for the model's first inference"
        assert first == [[1.0] + [0.0] * (warm.DIM - 1)]
        assert warm.embed(["a second prompt"], "query") == first
    finally:
        proc.kill()
        proc.wait(timeout=30)
        shutil.rmtree(room, ignore_errors=True)


# ---- t43 · PR 325 · remote-timeout-not-a-deadline ----------------------------------------------

# The warm server with a stand-in for the model: a query is answered at once, a batch of lesson texts
# (what `okl warm index` sends) keeps the one-request-at-a-time server busy for 2.5 s: five times what a
# prompt waits, and less than a person's command can be expected to wait. No model is loaded.
_T43_SERVER = (
    "import sys, time\n"
    "from okl import warm\n"
    "def load_model():\n"
    "    def encode(texts, kind):\n"
    "        if kind == 'doc':\n"
    "            time.sleep(2.5)\n"
    "        return [[1.0] + [0.0] * (warm.DIM - 1) for _ in texts]\n"
    "    return encode\n"
    "warm.load_model = load_model\n"
    "sys.exit(warm.serve())\n"
)


@pytest.mark.parametrize("command", ["status", "stop", "status-none", "stop-none", "prompt"])
def test_t43_pr325(tmp_path, monkeypatch, command):
    """`okl warm status` and `okl warm stop` asked while the warm server is busy with a long request (an index
    batch) wait for its answer rather than reading their own short timeout as no server: status says it is
    running (exit 0), and a stop the server obeys is not reported as unanswered, and the server exits.
    Control: with no server, status exits 1 and stop says none answered; and a prompt's own request to the
    busy server still gives up within its short budget, as a prompt cannot wait."""
    import shutil
    import tempfile
    import threading
    import time

    from okl import warm
    room = tempfile.mkdtemp(prefix="okl-t43-", dir="/tmp")     # a short path: a Unix socket's is limited
    sock = f"{room}/w.sock"
    monkeypatch.setenv("OKL_WARM_SOCKET", sock)
    try:
        if command.endswith("-none"):
            ran = _okl(tmp_path, "warm", command.removesuffix("-none"), OKL_WARM_SOCKET=sock)
            if command == "status-none":
                assert ran.returncode == 1, (ran.returncode, ran.stdout[-300:])
            else:
                assert "no server answered" in ran.stdout, ran.stdout[-300:]
            return
        log = tmp_path / "server.log"
        with log.open("w") as out:
            proc = subprocess.Popen([sys.executable, "-c", _T43_SERVER], env=_env(OKL_WARM_SOCKET=sock),
                                    stdout=out, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while warm.ping() is None:
                assert proc.poll() is None, f"the server exited: {log.read_text()[-400:]}"
                assert time.monotonic() < deadline, "the server never answered"
                time.sleep(0.05)
            def index_batch():
                with contextlib.suppress(warm.WarmUnavailableError):   # a stopped server may drop it
                    warm.embed(["a lesson"], "doc", timeout=30)
            busy = threading.Thread(target=index_batch, daemon=True)
            busy.start()
            time.sleep(0.3)        # the server is now inside the 2.5 s batch

            if command == "prompt":
                asked = time.monotonic()
                with contextlib.suppress(warm.WarmUnavailableError):
                    warm.embed(["add pagination to the orders list"], "query")
                waited = time.monotonic() - asked
                assert waited < 2.0, f"a prompt waited {waited:.1f} s on a busy server"
                busy.join(timeout=15)
                return
            ran = _okl(tmp_path, "warm", command, OKL_WARM_SOCKET=sock)

            if command == "status":
                assert ran.returncode == 0, f"a busy server read as not running: {ran.stdout[-300:]}"
            else:
                assert ran.returncode == 0, ran.stderr[-300:]
                assert "no server answered" not in ran.stdout, f"a stop the busy server obeyed: {ran.stdout[-300:]}"
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pytest.fail("the server did not stop")
            busy.join(timeout=15)
        finally:
            proc.kill()
            proc.wait(timeout=30)
    finally:
        shutil.rmtree(room, ignore_errors=True)


# ---- t44 · PR 383 · n_b4050b826687 -------------------------------------------------------------

@pytest.mark.parametrize(("label", "refused"), [
    ("UserPromptSubmit briefs the task", False),          # registered events: the diagram is right
    ("PostToolUse on Read briefs the file", False),
    ("Stop asks what was learned", False),
    ("SessionStart loads the store", True),               # a real event okl registers no hook for
    ("UserPromptSubmitted briefs the task", True),        # misspelt events: no such hook exists
    ("PostToolUsed on Read briefs the file", True),
    ("PreToolCall checks the edit", True),
    ("SessionBegin loads the store", True),
])
def test_t44_pr383(tmp_path, label, refused):
    """The diagram name check holds every hook event a diagram shows to the hooks okl registers, not only the
    event names it already knows: a misspelt or invented event fails it (exit 1), as an unregistered real
    one does. Control: a diagram naming only registered events passes (exit 0)."""
    source = tmp_path / "d.excalidraw"
    source.write_text(json.dumps({"type": "excalidraw", "elements": [{"type": "text", "text": label}]}))

    ran = _run([sys.executable, str(ROOT / "ci" / "check-diagram-names.py"), str(source)], ROOT)

    assert "Traceback" not in ran.stderr, ran.stderr[-400:]
    assert ran.returncode == (1 if refused else 0), (label, ran.returncode, ran.stdout[-400:])


# ---- t45 · PR 362 · n_713b8c104f12 -------------------------------------------------------------

@pytest.mark.parametrize("where", ["local", "service", "service-route"])
def test_t45_pr362(where, tmp_path, monkeypatch, request):
    """A check by paths given no paths at all checked nothing, so it is refused, not answered as a clean check
    that no lesson governs the files: Client.check raises, locally and over a service, and the service's
    /check answers such a request with a client error. Control: a check of a governed file still names its
    lesson, by each of the same routes."""
    from okl.client import Client
    if where == "local":
        repo = _git_repo(tmp_path / "repo", {"src/orders.py": "def get(): ...\n"})
        _configure(repo, "r")
        made = _okl(repo, "record", "--type", "Rule", "--scope", "repo", "--id", "orders-rule", "--title",
                    "orders rule", "--files", "src/orders.py", "--fix", "do the orders thing")
        assert made.returncode == 0, made.stderr[-300:]
        monkeypatch.chdir(repo)
    else:
        from okl import core
        service = request.getfixturevalue("_service")
        core.record(service.store, id="orders-rule", type="Rule", title="orders rule", scope="org",
                    files="src/orders.py", fix="do the orders thing", symptom="when orders")
    if where == "service-route":
        governed = service.api.post("/check", json={"repo": "r", "task": "", "paths": ["src/orders.py"]})
        assert governed.status_code == 200 and "orders-rule" in _ids(governed.json()), governed.text[-300:]
        empty = service.api.post("/check", json={"repo": "r", "task": "", "paths": []})
        assert 400 <= empty.status_code < 500, f"/check with no paths answered {empty.status_code}: {empty.text[-300:]}"
        return

    assert "orders-rule" in _ids(Client().check("", paths=["src/orders.py"]))
    try:
        answer = Client().check("", paths=[])
    except Exception:  # noqa: BLE001 - whatever the client raises is the refusal this asks for
        answer = None
    assert answer is None, f"a check of no files was answered as a clean check: {answer}"


# ---- t46 · PR 339 · owned-file-features-check-the-kept-copy ------------------------------------

def _t46_workflow(edit):
    """okl's shipped CI workflow, edited by hand as a team might: "comment" drops the install step's
    commands that read the pin but keeps its comments (which name the pin file), "other-step" drops the whole
    step's reading and has another step print the pin file, "diagnostic-step" has a later step show the
    installed package (naming it) and print the pin file, "python" only moves the Python version, so the
    install step still reads the pin."""
    lines = (ROOT / "src" / "okl" / "scaffold" / "ci" / "okl-verify.yml").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- name: Install okl")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("- name:"))
    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
    if edit == "python":
        return "\n".join(lines).replace('python-version: "3.13"', 'python-version: "3.12"', 1) + "\n"
    step = [lines[start], f"{indent}  run: |"]
    if edit == "comment":
        step += [line for line in lines[start + 1:end] if line.strip().startswith("#")]
    step.append(f"{indent}    pip install observed-knowledge-ledger")
    if edit == "other-step":
        step += [f"{indent}- name: Show the pinned okl", f"{indent}  run: cat .github/okl-version || true"]
    if edit == "diagnostic-step":
        step += [f"{indent}- name: Show what was installed", f"{indent}  run: |",
                 f"{indent}    pip show observed-knowledge-ledger", f"{indent}    cat .github/okl-version"]
    return "\n".join(lines[:start] + step + lines[end:]) + "\n"


# "diagnostic-step" was added from code review on #477, after the alternatives check: a fix that took any step
# naming the package for the install step counted a later diagnostic step's `cat` of the pin as reading it.
@pytest.mark.parametrize(("edit", "pinned"), [("comment", False), ("other-step", False), ("diagnostic-step", False),
                                              ("python", True), (None, True)])
def test_t46_pr339(tmp_path, edit, pinned):
    """`okl init --ci` writes the CI pin (.github/okl-version) only when the workflow it keeps actually installs
    okl from it: a kept, edited workflow whose install step no longer reads the pin gets none, though a comment
    in that step, or another step (one that also names the package), still names the file. Control: an edit elsewhere in the workflow, and okl's
    own unedited workflow, still get the pin of this release. okl runs as a release installed from an index,
    which is the only install that pins."""
    import okl
    version = okl.__version__ if re.fullmatch(r"\d+(\.\d+)+", okl.__version__ or "") else "0.11.0"
    site = tmp_path / "site" / f"observed_knowledge_ledger-{version}.dist-info"
    site.mkdir(parents=True)
    (site / "METADATA").write_text(f"Metadata-Version: 2.1\nName: observed-knowledge-ledger\nVersion: {version}\n")
    files = {"a.py": "x = 1\n"}
    if edit is not None:
        files[".github/workflows/okl-verify.yml"] = _t46_workflow(edit)
    repo = _git_repo(tmp_path / "repo", files)

    ran = _run([sys.executable, "-m", "okl", "init", "--repo", "r", "--ci"], repo,
               _env(PYTHONPATH=f"{tmp_path / 'site'}{os.pathsep}{SRC}"))

    assert ran.returncode == 0, ran.stderr[-400:]
    pin = repo / ".github" / "okl-version"
    if pinned:
        assert pin.is_file() and pin.read_text().strip() == version, (edit, ran.stdout[-600:])
    else:
        assert not pin.exists(), f"{edit}: a pin written beside a workflow whose install step never reads it"


# ---- t47 · PR 388 · n_5ddb0776a863 -------------------------------------------------------------

_T47_PR = {
    "number": 7, "title": "Fix the price check", "url": "https://github.com/o/r/pull/7", "state": "MERGED",
    "commits": {"nodes": [{"commit": {"oid": "3333333ccccccc", "committedDate": "2026-11-01T14:00:00Z",
                                       "messageHeadline": "price from the catalogue"}}]},
    "reviewThreads": {"nodes": [{
        "isResolved": True, "path": "app/orders.py", "line": 41, "originalLine": 40,
        "resolvedBy": {"login": "coderabbitai"},
        "comments": {"nodes": [
            {"author": {"login": "coderabbitai"}, "createdAt": "2026-11-01T11:00:00Z",
             "url": "https://github.com/o/r/pull/7#discussion_r1",
             "body": "**Don't trust the client's price for an order.**\n\nThe handler saves `price` as sent."},
            {"author": {"login": "dev"}, "createdAt": "2026-11-01T14:05:00Z", "url": "",
             "body": "Fixed in 3333333: the price comes from the catalogue."}]}}]},
}
# `okl intake pr 7` with GitHub's answer replaced by the recorded PR above: no network, one finding.
_T47_INTAKE = ("import json, sys\nfrom okl import intake\nfrom okl.cli import main\n"
               "pr = json.load(open(sys.argv[1]))\n"
               "intake.fetch = lambda number, repo=None: (pr, lambda sha: set())\n"
               "sys.exit(main(['intake', 'pr', '7']))\n")


def _t47_intake(tmp_path, name, config, lesson=False):
    """Run okl intake in a fresh repo named `name` configured with `config`; its exit, stdout and stderr."""
    repo = tmp_path / name
    (repo / ".okl").mkdir(parents=True)
    (repo / ".okl" / "config.json").write_text(json.dumps(config))
    if lesson:
        made = _okl(repo, "record", "--id", "price-from-catalogue", "--type", "Defect", "--scope", "repo",
                    "--title", "Never trust the price the client sends for an order",
                    "--symptom", "an order is saved with the client's price",
                    "--fix", "read the price from the catalogue on the server")
        assert made.returncode == 0, made.stderr[-300:]
    pr_file = tmp_path / f"{name}-pr.json"
    pr_file.write_text(json.dumps(_T47_PR))
    ran = _run([sys.executable, "-c", _T47_INTAKE, str(pr_file)], repo, timeout=120)
    assert "Traceback" not in ran.stderr, ran.stderr[-600:]
    return ran


def test_t47_pr388(tmp_path):
    """When the lessons a briefing would name for each finding cannot be looked up (the store, here a shared
    service, does not answer), okl intake says so: its output is not the same as for a store that answered
    and holds no covering lesson, which would make every finding read as one nothing covers. Control: the
    worksheet is still printed (exit 0), and with a store that holds a covering lesson, intake names it."""
    covered = _t47_intake(tmp_path, "covered", {"repo": "r"}, lesson=True)
    assert covered.returncode == 0 and "price-from-catalogue" in covered.stdout, covered.stdout[-400:]

    empty = _t47_intake(tmp_path, "empty", {"repo": "r"})
    down = _t47_intake(tmp_path, "down", {"repo": "r", "service_url": "http://127.0.0.1:9"})

    assert empty.returncode == 0 and down.returncode == 0, (empty.stderr[-300:], down.stderr[-300:])
    assert "Don't trust the client's price" in down.stdout, down.stdout[-400:]
    said = set((down.stdout + down.stderr).splitlines()) - set((empty.stdout + empty.stderr).splitlines())
    assert said, "a lookup that could not run reads exactly like a store with no covering lesson"


# ---- t48 · PR 77 · hook-cli-version-skew · control ---------------------------------------------

# Stand-ins for the okl CLI the prompt hook runs. "old" is an okl from before --format hook: argparse refuses
# the new choice (exit 2) and briefs in the agent format. "new" knows --format hook. "down" cannot run a
# check at all, whatever it is asked.
_T48_STUBS = {
    "old": ('case "$*" in\n'
            '  *"--format hook"*) echo "usage: okl check [-h] [--task TASK] [--format {agent,json}]" >&2\n'
            "    echo \"okl check: error: argument --format: invalid choice: 'hook' (choose from 'agent', 'json')\" >&2\n"
            "    exit 2 ;;\n"
            '  *"--format agent"*) echo "BRIEFING t48 from the older okl"; exit 0 ;;\n'
            "esac\nexit 2\n"),
    "new": ('case "$*" in\n'
            '  *"--format hook"*) echo \'{"hookSpecificOutput": {"additionalContext": "BRIEFING t48 hook"}}\'; exit 0 ;;\n'
            "esac\nexit 2\n"),
    "down": 'echo "OKL UNREACHABLE: the store at sqlite:///gone.db cannot be read" >&2\nexit 2\n',
}


@pytest.mark.parametrize("cli", ["old", "new", "down"])
def test_t48_pr77(tmp_path, cli):
    """The prompt hook survives an okl older than itself: when okl refuses --format hook as an invalid choice,
    the hook briefs in the format that okl knows instead of blocking the prompt. Control: a current okl's
    hook output is passed on as it is, and an okl that cannot run a check still blocks the prompt (exit 2)."""
    repo = tmp_path / "repo"
    (repo / ".okl").mkdir(parents=True)
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    stub = tmp_path / "okl-stub"
    stub.write_text("#!/bin/bash\n" + _T48_STUBS[cli])
    stub.chmod(0o755)
    env = _env(CLAUDE_PROJECT_DIR=str(repo), OKL_BIN=str(stub))

    ran = _run(["bash", str(ROOT / "hooks" / "userpromptsubmit-okl-check.sh")], repo, env,
               input=json.dumps({"prompt": "add pagination to the orders list"}), timeout=120)

    if cli == "down":
        assert ran.returncode == 2, (ran.returncode, ran.stdout[-300:])
        return
    assert ran.returncode == 0, f"{cli} okl: the prompt was blocked: {ran.stderr[-400:]}"
    assert f"BRIEFING t48 {'from the older okl' if cli == 'old' else 'hook'}" in ran.stdout, ran.stdout[-400:]
