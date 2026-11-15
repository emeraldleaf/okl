"""REPORT §4bg's graders, by behaviour: one per task of evals/replay-tasks-4bg.json.

Each asks what the stored lesson asks of the change, through what the code offers at the frozen commit
(the CLI, a returned briefing, the shipped script), never through a function, flag, field or message the
real fix invented, so any correct fix passes and no agent has to guess a name. Each has a positive control,
so a "fix" that simply refuses or does nothing fails too. t15-t18 are controls: the frozen code already
follows the lesson, so they pass as it stands and fail only once that behaviour is taken out.

Copied into a room as tests/test_replay_grader.py, and run with the room as cwd and its src on PYTHONPATH.
Standard library, pytest and okl only; every helper a grader needs is in this file.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
import types
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


# ---- t01 · PR 388 · eval-scripts-no-exposure ----------------------------------------------------

_PRICE_PR = {
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
_INTAKE = ("import json, sys\nfrom okl import intake\nfrom okl.cli import main\n"
           "pr = json.load(open(sys.argv[1]))\n"
           "intake.fetch = lambda number, repo=None: (pr, lambda sha: set())\n"
           "sys.exit(main(['intake', 'pr', '7']))\n")


def test_t01_pr388(tmp_path, monkeypatch):
    """The lookup `okl intake` makes to name the lesson that already covers a finding briefs no agent, so it
    must not count as one: no briefing row afterwards. Control: the lesson is still named, and an agent's own
    briefing is still logged. Intake runs in its own process, so a fix that switches logging off in-process
    cannot reach the control."""
    from okl.client import Client
    from okl.store import Store
    monkeypatch.chdir(tmp_path)
    url = _configure(tmp_path, "r")
    Client().record(id="price-from-catalogue", type="Defect", scope="repo",
                    title="Never trust the price the client sends for an order",
                    symptom="an order is saved with the client's price",
                    fix="read the price from the catalogue on the server",
                    triggers=["don't trust the client's price for an order"])
    pr_file = tmp_path / "pr.json"
    pr_file.write_text(json.dumps(_PRICE_PR))

    ran = _run([sys.executable, "-c", _INTAKE, str(pr_file)], tmp_path)

    assert ran.returncode == 0, ran.stderr[-400:]
    assert "price-from-catalogue" in ran.stdout, ran.stdout[-400:]        # control: the lookup still names it
    store = Store(url)
    assert store.briefings() == [], "intake's lookup was logged as a briefing no agent saw"
    store.close()
    Client().check("don't trust the client's price for an order")         # control: an agent's briefing is logged
    store = Store(url)
    assert len(store.briefings()) == 1
    store.close()


# ---- t02 · PR 383 · n_0637c92c032f --------------------------------------------------------------

def _svg(*lines):
    """An exported render holding `lines`, one <text> each, as Excalidraw writes them."""
    texts = "".join(f'<text x="0" y="16" font-size="16px" style="white-space: pre;">{_xml(t)}</text>' for t in lines)
    return f'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g>{texts}</g></svg>'


def _xml(text):
    """`text` escaped as an SVG writes it."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@pytest.mark.parametrize(("render", "refused"), [
    (["okl check --task x", "the briefing"], False),                  # the render agrees with its source
    (["okl record --task x", "the briefing"], True),                  # a stale render: other real names
    (["okl check --task x", "the briefing", "okl_teleport"], True),   # a name only the render shows
])
def test_t02_pr383(tmp_path, render, refused):
    """The diagram check also reads the render people see. A render that agrees with its .excalidraw passes
    (exit 0); one that names other things than its source, or a name the code lacks that only it shows, fails
    (exit 1, not a crash)."""
    source = tmp_path / "d.excalidraw"
    source.write_text(json.dumps({"type": "excalidraw", "elements": [
        {"type": "text", "text": "okl check --task x"}, {"type": "text", "text": "the briefing"}]}))
    (tmp_path / "d.svg").write_text(_svg(*render))

    ran = _run([sys.executable, str(ROOT / "ci" / "check-diagram-names.py"), str(source)], ROOT)

    assert "Traceback" not in ran.stderr, ran.stderr[-400:]
    assert ran.returncode == (1 if refused else 0), (ran.returncode, ran.stdout[-400:])


# ---- t03 · PR 37 · n_e7988ff536fb ---------------------------------------------------------------

_STAMP = "2026-09-21T14:14Z"
_RULE = {"id": "n1", "type": "Rule", "title": "t", "scope": "org", "files": "a.py",
         "verified_at": 1_790_000_040_000, "verified_by": f"`true` exit 0 @ {_STAMP}"}


@pytest.mark.parametrize(("rules", "refused"), [
    ([_RULE], False),              # well formed: the gate runs, and finds what it finds (0 or 1)
    ("x", True),                   # `rules` is not a list
    (["not an entry"], True),      # an entry that is not an object
    ([None], True),
])
def test_t03_pr37(tmp_path, rules, refused):
    """A hand-edited drift snapshot that is malformed is refused with exit 2 ("did not run"), never a traceback:
    a traceback exits 1, which `--gate` reads as drift found. Control: a well-formed snapshot is not refused."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n", "okl-drift.json": json.dumps(
        {"format": "okl-drift-snapshot/1", "repo": "r", "rules": rules})})

    ran = _okl(repo, "drift", "--gate", "--snapshot", "okl-drift.json")

    assert "Traceback" not in ran.stderr, ran.stderr[-400:]
    if refused:
        assert ran.returncode == 2, (ran.returncode, ran.stdout[-300:], ran.stderr[-300:])
    else:
        assert ran.returncode in (0, 1), (ran.returncode, ran.stderr[-300:])


# ---- t04 · PR 380 · n_02cc84da158d --------------------------------------------------------------

@pytest.mark.parametrize("url", [None, ""])
def test_t04_pr380(tmp_path, url):
    """`okl doctor` in a repo whose store does not exist yet creates none, whether OKL_DATABASE_URL is unset or
    empty (the client reads empty as unset). Control: once the store exists, doctor still reports what the
    repo's interests hide."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    env = {} if url is None else {"OKL_DATABASE_URL": url}
    assert _okl(repo, "init", "--repo", "r", "--no-claude", "--no-seed", "--no-ci", "--interests",
                "python").returncode == 0
    db = repo / ".okl" / "okl.db"
    db.unlink(missing_ok=True)

    ran = _okl(repo, "doctor", **env)

    assert ran.returncode in (0, 1), ran.stderr[-300:]
    assert not db.exists(), f"doctor created a store with OKL_DATABASE_URL={url!r}"
    assert "interests" not in ran.stdout
    rec = _okl(repo, "record", "--type", "Rule", "--scope", "org", "--title", "A security lesson", "--body",
               "something to know", "--tags", "security", **env)
    assert rec.returncode == 0, rec.stderr[-300:]
    after = _okl(repo, "doctor", **env)
    assert after.returncode in (0, 1) and "interests" in after.stdout, after.stdout[-400:]


# ---- t05 · PR 259 · filter-after-fetch-widens-window --------------------------------------------

def _weak_first_store():
    """A store whose ranking puts every record sharing one word with the task ahead of the one sharing both."""
    from okl.store import Store

    class WeakFirst(Store):
        def search(self, query, limit=20, **kw):
            offset = kw.pop("offset", 0)
            rows = super().search(query, limit=500 + offset, **kw)
            rows.sort(key=lambda n: n.title == "money handling")     # the strong one last
            return rows[offset:offset + limit]
    return WeakFirst("sqlite:///:memory:")


@pytest.mark.parametrize("weak_first", [True, False])
def test_t05_pr259(weak_first):
    """When the first window of the search holds only weak matches, the briefing still finds the record that
    qualifies, ranked just past it: not 'no close match'. The weak ones stay out. Control: with the natural
    ranking the same record is found."""
    from okl import core
    from okl.store import Store
    s = _weak_first_store() if weak_first else Store("sqlite:///:memory:")
    fillers = {core.record(s, type="Rule", title=f"filler rule {i}", scope="org", body="the price is set")
               for i in range(40)}
    wanted = core.record(s, type="Rule", title="money handling", scope="org", body="the catalogue sets the price")

    res = core.check(s, repo="r", task="price catalogue")

    assert wanted in _ids(res), "a qualifying record just past the first window read as no match"
    assert not fillers & _ids(res), "the weak matches the floor drops came back"
    assert res["match_count"] == 1


# ---- t06 · PR 163 · filter-after-fetch-widens-window --------------------------------------------

def _retire_store(retired):
    """A store with `retired` obsolete lessons ranking above one live one, all matching 'refund ledger'."""
    from okl import core
    from okl.store import Store
    s = Store("sqlite:///:memory:")
    for i in range(retired):
        core.record(s, id=f"gone{i}", type="Rule", title="refund ledger refund ledger", scope="org", fix="f")
    core.record(s, id="live", type="Rule", title="refund ledger", scope="org", fix="f")
    for i in range(retired):
        core.retire(s, f"gone{i}", "gone", obsolete=True)
    return s


@pytest.mark.parametrize("retired", [3, 0])
def test_t06_pr163(retired):
    """Retired lessons do not use up the search window: with three obsolete matches above the one live one, a
    briefing of one slot still shows the live one, and never a retired one. Control: with none retired, the same."""
    from okl import core
    s = _retire_store(retired)

    res = core.check(s, "r", "refund ledger", limit=1)

    assert [r["id"] for r in res["rules"]] == ["live"], _ids(res)
    assert not any(i.startswith("gone") for i in _ids(res))


# ---- t07 · PR 163 · importer-keeps-local-decision -----------------------------------------------

def _pack(path, other_title):
    """A seed pack of two lessons that both say status live."""
    path.write_text(json.dumps({"nodes": [
        {"key": "grid", "type": "Rule", "scope": "org", "repo": "r", "title": "Grid", "status": "live"},
        {"key": "other", "type": "Rule", "scope": "org", "repo": "r", "title": other_title, "status": "live"}]}))


def test_t07_pr163(tmp_path):
    """A retirement made locally survives a re-seed of a pack that sets the lesson's status. Control: the
    re-seed still imports everything else (another lesson's new title) and a lesson never retired stays live."""
    from okl.store import Store
    _configure(tmp_path, "r")
    pack = tmp_path / "site.json"
    _pack(pack, "Other v1")
    assert _okl(tmp_path, "seed", str(pack)).returncode == 0
    assert _okl(tmp_path, "retire", "seed:site:grid", "--obsolete", "--reason", "gone").returncode == 0
    _pack(pack, "Other v2")

    assert _okl(tmp_path, "seed", str(pack)).returncode == 0

    store = Store(f"sqlite:///{tmp_path / '.okl' / 'okl.db'}")
    assert store.get_node("seed:site:grid").status == "obsolete", "the re-seed brought a retired lesson back"
    assert store.get_node("seed:site:other").title == "Other v2"
    assert store.get_node("seed:site:other").status in (None, "", "live")
    store.close()


# ---- t08 · PR 307 · n_916330f61994 --------------------------------------------------------------

_READ_ONLY_TOOLS = {"cat", "ls", "head", "tail", "wc", "pwd", "grep", "stat"}
_GIT_READS = {"merge-base", "rev-parse", "log", "show", "diff", "rev-list", "cat-file", "ls-tree", "ls-files",
              "status", "blame", "diff-tree", "describe", "show-ref"}


def _tree_state(root):
    """Every file under `root` with its content, to see whether a command wrote anything."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.name not in ("index", "index.lock")}


def test_t08_pr307(tmp_path):
    """The review agent's allow-list, as the workflow writes it, holds only commands that cannot write: run each
    allowed git form with the arguments a model could add (--output, a ref name to create, a config value) in a
    scratch repository, and nothing may change. Control: a git read form is still allowed, so the agent can
    still check a commit is reachable."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    entries = re.findall(r'"Bash\(([^"]*)\)"', text)
    assert entries, "no Bash allow-list found in the workflow"
    repo = _git_repo(tmp_path / "scratch", {"a.txt": "x\n"})
    reads = 0
    for entry in entries:
        wild = entry.endswith(":*")
        argv = shlex.split(entry[:-2] if wild else entry)
        if argv[0] != "git":
            assert argv[0] in _READ_ONLY_TOOLS, f"cannot show that {entry!r} cannot write"
            continue
        reads += argv[1] in _GIT_READS
        probes = [["--output=" + str(repo / "pwned.txt")], ["--output", str(repo / "pwned.txt")],
                  ["pwnref"], ["user.pwn", "1"], ["-d", "pwnref"]] if wild else [[]]
        for extra in probes:
            before = _tree_state(repo)
            subprocess.run([*argv, *extra], cwd=repo, env=_env(), capture_output=True, text=True, timeout=60)
            assert _tree_state(repo) == before, f"{entry!r} allowed `{' '.join([*argv, *extra])}`, which writes"
    assert reads, "no git read form is allowed any more"


# ---- t09 · PR 362 · remote-path-test-through-client ---------------------------------------------

def test_t09_pr362(_service, tmp_path):
    """Over a service, a check of files that all lie outside the repo is answered (nothing there can be
    governed), not refused: no error, no match, the paths named as outside. Control: a path inside the repo is
    still answered by the service, alone and beside one outside."""
    from okl import core
    from okl.client import Client
    core.record(_service.store, id="orders-rule", type="Rule", title="orders rule", scope="org",
                files="src/orders.py", fix="do the orders thing", symptom="when orders")

    try:
        outside, refused = Client().check("", paths=["/etc/hosts"]), None
    except Exception as e:  # noqa: BLE001 - whatever the client raises is the refusal this asserts is gone
        outside, refused = None, e

    assert refused is None, f"the check was refused: {refused}"
    assert outside["outside_repo"] == ["/etc/hosts"] and outside["match_count"] == 0
    inside = Client().check("", paths=["src/orders.py"])
    assert "orders-rule" in _ids(inside)
    mixed = Client().check("", paths=["src/orders.py", "/etc/hosts"])
    assert "orders-rule" in _ids(mixed) and mixed["outside_repo"] == ["/etc/hosts"]


# ---- t10 · PR 34 · n_e7988ff536fb ---------------------------------------------------------------

def _drift_step():
    """The shell of the shipped CI step that runs `okl drift --gate`."""
    lines = (ROOT / "ci" / "okl-verify.yml").read_text().splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.strip().startswith("okl drift"))
    run_at = max(i for i in range(at) if lines[i].strip() == "run: |")
    indent = len(lines[run_at + 1]) - len(lines[run_at + 1].lstrip())
    block = []
    for ln in lines[run_at + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) < indent:
            break
        block.append(ln[indent:])
    return "\n".join(block)


@pytest.mark.parametrize(("okl_exit", "service_url", "step_exit", "warns"), [
    (0, None, 0, False), (1, None, 1, False), (2, None, 0, True),     # no store: "did not run" is a warning
    (2, "", 0, True),                                                 # an unset secret reaches the job empty
    (0, "https://store.example", 0, False), (1, "https://store.example", 1, False),
    (2, "https://store.example", 2, None),                            # a store IS configured: it is an outage
])
def test_t10_pr34(tmp_path, okl_exit, service_url, step_exit, warns):
    """Run the shipped drift step's own shell against a stub okl that exits as told. Findings fail the job and a
    clean run passes; exit 2 (did not run) is a warning only when the job was given no store (no value, or an
    empty one: an unset secret), and fails the job when one is configured, where passing would hide an outage
    behind green."""
    stub = tmp_path / "okl"
    stub.write_text(f"#!/bin/sh\nexit {okl_exit}\n")
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_SERVICE_URL", "OKL_DATABASE_URL")}
    env["PATH"] = f"{tmp_path}:{os.environ['PATH']}"
    if service_url is not None:
        env["OKL_SERVICE_URL"] = service_url

    ran = subprocess.run(["bash", "-euo", "pipefail", "-c", _drift_step()], capture_output=True, text=True,
                         env=env, cwd=tmp_path)

    assert ran.returncode == step_exit, (okl_exit, service_url, ran.returncode, ran.stdout[-300:])
    if warns is not None:
        assert ("::warning" in ran.stdout) is warns


# ---- t11 · PR 163 · remote-timeout-not-a-deadline -----------------------------------------------

def test_t11_pr163(tmp_path, monkeypatch):
    """Retiring a lesson twice with the identical request (what a retry after a lost answer does) leaves one
    row in its history, and both calls succeed. Control: the first call logs a row, and a different reason is a
    new retirement and is logged."""
    from okl.client import Client
    from okl.store import Store
    monkeypatch.chdir(tmp_path)
    url = _configure(tmp_path, "r")
    c = Client()
    c.record(id="a", type="Rule", title="a", scope="org")
    c.record(id="b", type="Rule", title="b", scope="org")

    def rows():
        store = Store(url)
        try:
            return [(r.kind, r.by) for r in store.retirements("a")]
        finally:
            store.close()

    assert _okl(tmp_path, "retire", "a", "--by", "b", "--reason", "replaced").returncode == 0
    assert rows() == [("superseded", "b")]
    assert _okl(tmp_path, "retire", "a", "--by", "b", "--reason", "replaced").returncode == 0
    assert rows() == [("superseded", "b")], "an identical retry wrote another row"
    assert _okl(tmp_path, "retire", "a", "--by", "b", "--reason", "replaced, and here is why").returncode == 0
    assert len(rows()) == 2


# ---- t12 · PR 363 · temp-marker-keyed-by-scope --------------------------------------------------

def _checkout(path, repo, fix):
    """A git checkout named `repo`, with its own store holding one verified lesson governing src/orders.py."""
    _git_repo(path, {"src/orders.py": "def get(): ...\n"})
    _configure(path, repo)
    made = _okl(path, "record", "--type", "Rule", "--scope", "repo", "--id", "ledger-audit", "--title",
                "Every ledger read goes through the audit trail", "--files", "src/orders.py", "--fix", fix)
    assert made.returncode == 0, made.stderr[-300:]
    proved = _okl(path, "verify", "ledger-audit", "--run", "true", "--expect", "")
    assert proved.returncode == 0, proved.stderr[-300:]
    return path


def _briefed(path, session, tmp):
    """The lesson ids `okl check --path` returns for src/orders.py in `session`, run from `path`."""
    ran = _okl(path, "check", "--path", "src/orders.py", "--session", session, "--format", "json", TMPDIR=str(tmp))
    assert ran.returncode == 0, ran.stderr[-300:]
    return _ids(json.loads(ran.stdout))


def test_t12_pr363(tmp_path):
    """A file briefing leaves out a lesson already briefed in the session, but only in the checkout that briefed
    it: another checkout (another directory, another repo, its own store) given the same session id is briefed.
    Control: the same checkout is not briefed twice, and another session starts afresh."""
    shared_tmp = tmp_path / "tmp"
    shared_tmp.mkdir()
    api = _checkout(tmp_path / "api", "api", "call audit_trail_7Q before returning entries")
    web = _checkout(tmp_path / "web", "web", "call audit_trail_9Z before returning entries")

    assert "ledger-audit" in _briefed(api, "s1", shared_tmp)
    assert "ledger-audit" not in _briefed(api, "s1", shared_tmp), "the dedupe is gone"
    assert "ledger-audit" in _briefed(api, "s2", shared_tmp), "another session was not briefed"
    assert "ledger-audit" in _briefed(web, "s1", shared_tmp), "another checkout lost the lesson"


# ---- t13 · PR 161 · remote-path-test-through-client ---------------------------------------------

def _mcp_record(**args):
    """Call the MCP server's okl_record tool in-process; the outcome is read from the store, not the text."""
    from okl.mcp_server import _build

    async def call():
        return await _build().call_tool("okl_record", args)
    with contextlib.suppress(Exception):   # a tool that raises has not recorded; the caller reads the store
        asyncio.run(call())


@pytest.mark.parametrize("path", ["slash", "mcp"])
def test_t13_pr161(_service, capsys, path):
    """Over a service, through the real client: an id containing a slash can be shown and updated, and a lesson
    recorded through the MCP tool is stored (with an id and without one). Control: an id without a slash works
    the same way."""
    from okl.cli import main
    if path == "slash":
        for lesson in ("auth/idor", "plain"):
            assert main(["record", "--id", lesson, "--type", "Rule", "--scope", "org", "--title", "t"]) == 0
            capsys.readouterr()
            assert main(["show", lesson]) == 0
            assert f"[{lesson}]" in capsys.readouterr().out
            assert main(["update", lesson, "--fix", "g"]) == 0
            assert _service.store.get_node(lesson).fix == "g"
    else:
        _mcp_record(type="Rule", title="with an id", scope="org", id="m1")
        _mcp_record(type="Rule", title="without one", scope="org")
        assert _service.store.get_node("m1") is not None, "a record over MCP to a service was not stored"
        assert "without one" in {n.title for n in _service.store.all_nodes()}


# ---- t14 · PR 363 · hook-cli-version-skew -------------------------------------------------------

_STUBS = {"bad-interpreter": "#!/no/such/interpreter\n", "exit-127": "#!/bin/sh\nexit 127\n",
          "exit-126": "#!/bin/sh\nexit 126\n"}


def _read_hook(tmp_path, okl_bin):
    """Run the shipped read hook after a Read of src/orders.py, with OKL_BIN naming `okl_bin`; PATH offers only
    a python3 that imports this checkout's okl. Returns its output."""
    repo = _git_repo(tmp_path / "repo", {"src/orders.py": "def get(): ...\n"})
    url = _configure(repo, "r")
    made = _okl(repo, "record", "--type", "Rule", "--scope", "repo", "--id", "ledger-audit", "--title",
                "Every ledger read goes through the audit trail", "--files", "src/orders.py",
                "--fix", "call audit_trail_7Q(account_id) before returning entries", OKL_DATABASE_URL=url)
    assert made.returncode == 0, made.stderr[-300:]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python3").symlink_to(sys.executable)
    stdin = json.dumps({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Read",
                        "tool_input": {"file_path": str(repo / "src" / "orders.py")}})
    env = _env(CLAUDE_PROJECT_DIR=str(repo), OKL_BIN=okl_bin, OKL_DATABASE_URL=url, TMPDIR=str(tmp_path),
               PATH=f"{bindir}:/usr/bin:/bin")
    return _run(["bash", str(ROOT / "hooks" / "posttooluse-okl-read.sh")], repo, env, input=stdin)


@pytest.mark.parametrize("stub", [None, "bad-interpreter", "exit-127", "exit-126"])
def test_t14_pr363(tmp_path, stub):
    """The read hook passes over an okl that resolves but cannot start (exit 126 or 127) for the next layer, as
    the prompt hook does, so the file's lesson still reaches the agent. Control: with a working okl pinned, the
    lesson arrives."""
    if stub is None:
        okl_bin = f"{sys.executable} -m okl"
    else:
        broken = tmp_path / "okl-broken"
        broken.write_text(_STUBS[stub])
        broken.chmod(0o755)
        okl_bin = str(broken)

    ran = _read_hook(tmp_path, okl_bin)

    assert ran.returncode == 0, ran.stderr[-300:]
    context = json.loads(ran.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "audit_trail_7Q" in context, context


# ---- t15 · PR 269 · eval-scripts-no-exposure · control -------------------------------------------

def test_t15_pr269(tmp_path, monkeypatch):
    """The harness's briefing for the indexed arm, and the tool-using generator's environment, ask okl for no
    briefing log: a real briefing fetched through the harness against a throwaway store leaves no briefing row,
    while the same command without the setting does (so the check can see a row)."""
    from okl.store import Store
    ab = _load("ab_harness")
    url = f"sqlite:///{tmp_path / 'store.db'}"
    task = "paginate the list with an offset query"
    made = _okl(tmp_path, "record", "--type", "Rule", "--title", "pagination", "--scope", "org", "--id", "p",
                "--symptom", "an offset query", OKL_DATABASE_URL=url)
    assert made.returncode == 0, made.stderr[-300:]
    monkeypatch.setenv("OKL_DATABASE_URL", url)

    ab.get_briefing(task, 120, index=True)

    store = Store(url)
    assert store.briefings() == [], "the indexed arm's briefing was logged as exposure"
    store.close()
    plain = _okl(ab.REPO, "check", "--task", task, "--format", "agent", "--interests", "", "--index",
                 OKL_DATABASE_URL=url)
    assert plain.returncode == 0, plain.stderr[-300:]
    store = Store(url)
    assert len(store.briefings()) == 1, "the check cannot see a logged briefing"
    store.close()
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    env = ab.generator_env(str(tmp_path), str(tmp_path / "shim.log"))
    assert env is not None and env.get("OKL_BRIEFING_LOG") == "0", "the generator's environment still logs briefings"


# ---- t16 · PR 274 · fastembed-cache-in-tmpdir · control ------------------------------------------

def test_t16_pr274(monkeypatch, tmp_path):
    """The reranker is loaded with its model kept under the user's cache home (XDG_CACHE_HOME, else ~/.cache),
    not fastembed's default in the system temp directory, and fastembed's own override is honoured."""
    from okl import rerank
    seen = {}

    class Encoder:
        def __init__(self, model_name, **kw):
            seen.update(cache_dir=kw.get("cache_dir"), env=os.environ.get("FASTEMBED_CACHE_PATH"))

    fake = types.ModuleType("fastembed.rerank.cross_encoder")
    fake.TextCrossEncoder = Encoder
    for name, mod in (("fastembed", types.ModuleType("fastembed")),
                      ("fastembed.rerank", types.ModuleType("fastembed.rerank")),
                      ("fastembed.rerank.cross_encoder", fake)):
        monkeypatch.setitem(sys.modules, name, mod)

    def kept(label):
        seen.clear()
        rerank.load_model(f"model-{label}-{os.getpid()}")
        return Path(seen.get("cache_dir") or seen["env"] or "").resolve()

    xdg, home = tmp_path / "xdg", tmp_path / "home"
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    assert kept("xdg").is_relative_to(xdg.resolve()), seen
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(home))
    assert kept("home").is_relative_to((home / ".cache").resolve()), seen
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "theirs"))
    assert kept("theirs") == (tmp_path / "theirs").resolve()


# ---- t17 · PR 262 · harness-reads-a-moving-working-tree · control --------------------------------

class _Moved:
    """A stand-in for the harness's commit lookup: one commit when the run starts, another after."""

    def __init__(self, moves):
        self.moves, self.calls = moves, 0

    def __call__(self, *a, **k):
        self.calls += 1
        return "bbbbbbb" if self.moves and self.calls > 1 else "aaaaaaa"


@pytest.mark.parametrize("moves", [True, False])
def test_t17_pr262(monkeypatch, tmp_path, moves):
    """A harness run whose working tree changed commit between its start and its receipt is refused: a non-zero
    exit and a receipt marked not usable. Control: a run whose tree stayed put exits 0 with a usable receipt."""
    ab = _load("ab_harness")
    monkeypatch.setattr(ab, "GENERATOR_CMD", "claude -p --model sonnet")
    monkeypatch.setattr(ab, "JUDGE_CMD", "claude -p --model haiku")
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(ab, "RESULTS_DIR", results)
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps({"id": "t", "task": "x", "defect_node": ""}) + "\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".okl").mkdir()
    (work / ".okl" / "config.json").write_text('{"repo": "r"}')
    monkeypatch.chdir(work)
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{work / 'okl.db'}")
    monkeypatch.setattr(sys, "argv", ["ab_harness.py", "--tasks", str(tasks)])
    real_run = subprocess.run
    monkeypatch.setattr(ab.subprocess, "run", lambda cmd, *a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")
                        if any("preflight" in str(c) for c in cmd) else real_run(cmd, *a, **k))
    models = {"claude -p --model sonnet": ["claude-sonnet-5-5"], "claude -p --model haiku": ["claude-haiku-5-5"]}
    monkeypatch.setattr(ab, "resolved_model", lambda cmd, *a, **k: models[cmd])
    monkeypatch.setattr(ab, "get_briefing", lambda *a, **k: "b")
    monkeypatch.setattr(ab, "run_one", lambda t, arm, s, **k: ({"task": t["id"], "arm": arm, "sample": s,
                                                               "reproduced": False, "seconds": 0}, True))
    monkeypatch.setattr(ab, "_okl_commit", _Moved(moves))

    code = ab.main()

    receipt = json.loads(next(results.glob("ab-*.json")).read_text())
    if moves:
        assert code not in (0, None) and receipt["usable"] is False, (code, receipt["usable"])
    else:
        assert code == 0 and receipt["usable"] is True, (code, receipt["usable"])


# ---- t18 · PR 50 · n_58119d0a63d9 · control ------------------------------------------------------

def _okl_commands(settings):
    """Every hook command in a Claude Code settings file that names okl."""
    return [h.get("command", "") for groups in (settings.get("hooks") or {}).values() for g in groups
            for h in g.get("hooks", []) if "okl" in h.get("command", "")]


def test_t18_pr50(tmp_path):
    """`okl init` registers its hooks in .claude/settings.json itself, once however often it runs, beside another
    tool's hook it leaves alone; `okl init --uninstall` removes exactly those registrations, keeps the other
    tool's hook and never touches the store."""
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    (repo / ".claude").mkdir()
    other = {"type": "command", "command": "other-tool.sh"}
    settings_file = repo / ".claude" / "settings.json"
    settings_file.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [other]}],
                                                   "PostToolUse": [{"hooks": [other]}]}}))

    for _ in range(2):
        assert _okl(repo, "init", "--repo", "r").returncode == 0
    settings = json.loads(settings_file.read_text())
    registered = _okl_commands(settings)
    assert sorted(Path(c.replace('"', "")).name for c in registered) == [
        "stop-okl-encode.sh", "userpromptsubmit-okl-check.sh"], registered
    assert other in [h for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]

    assert _okl(repo, "init", "--uninstall").returncode == 0
    after = json.loads(settings_file.read_text())
    assert _okl_commands(after) == []
    assert other in [h for g in after["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert other in [h for g in after["hooks"]["PostToolUse"] for h in g["hooks"]]
    assert (repo / ".okl").is_dir()
