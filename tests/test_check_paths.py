"""`okl check --path`: the lessons that govern a file, asked before it is read or edited (#94)."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from okl import core
from okl.client import Client, OKLRejectedError
from okl.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _record(store, id, files, scope="org", type="Rule", **kw):
    core.record(store, id=id, type=type, title=f"lesson {id}", scope=scope, files=files,
                fix=f"do {id}", symptom=f"when {id}", **kw)


def test_check_paths_briefs_every_lesson_that_governs_the_file():
    """Matched by the files a lesson names, not by words: an exact path, a directory above it and
    a glob each govern; another repo's lesson, a retired one and one naming other files do not.
    Every governing lesson is briefed, in check()'s shape, so every format renders it."""
    store = Store("sqlite:///:memory:")
    _record(store, "exact", "src/orders.py")
    _record(store, "dir", "src/")
    _record(store, "glob", "src/*.py", scope="repo:r")
    _record(store, "defect", "src/orders.py", type="Defect")
    _record(store, "elsewhere", "docs/README.md")
    _record(store, "theirs", "src/orders.py", scope="repo:other")
    _record(store, "gone", "src/orders.py")
    core.retire(store, "gone", reason="obsolete", obsolete=True)

    result = core.check_paths(store, "r", ["src/orders.py"])

    briefed = {r["id"] for k in ("rules", "relevant_defects") for r in result[k]}
    assert briefed == {"exact", "dir", "glob", "defect"}
    assert result["paths"] == ["src/orders.py"] and result["match_count"] == 4
    assert {a["id"] for a in result["next_actions"]} == briefed
    text = core.render_check_for_agent(result)
    assert "files: src/orders.py" in text and "[exact]" in text and "[theirs]" not in text
    assert core.render_actions_only(result).startswith("OKL — 4 rule(s) govern src/orders.py:")

    none = core.check_paths(store, "r", ["README.md"])   # src/ is governed whole
    assert none["match_count"] == 0 and none["store_records"] > 0
    assert "No lesson governs these files" in core.render_check_for_agent(none)
    assert core.render_actions_only(none) == "OKL: no lesson governs README.md (r)."
    empty = core.check_paths(Store("sqlite:///:memory:"), "r", ["src/orders.py"])
    assert "store is EMPTY" in core.render_check_for_agent(empty)


def _repo(tmp_path):
    repo = tmp_path / "repo"; (repo / "src").mkdir(parents=True)
    local = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
    env = {k: v for k, v in os.environ.items() if k not in local}
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env)
    (repo / "src" / "orders.py").write_text("def get(): ...\n")
    (repo / ".okl").mkdir(); (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    subprocess.run(["git", "-C", str(repo), "add", "src"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)
    return repo, env


def _okl(tmp_path, cwd, env, *args):
    env = {**env, "OKL_DATABASE_URL": f"sqlite:///{tmp_path / 'store.db'}", "PYTHONPATH": str(ROOT / "src")}
    env.pop("OKL_SERVICE_URL", None)
    return subprocess.run([sys.executable, "-m", "okl", *args], cwd=cwd, env=env, capture_output=True, text=True)


def test_okl_check_path_from_the_cli(tmp_path):
    """A path relative to the working directory, absolute, or from a subdirectory names the same
    file; the lesson comes with its drift mark (governed files, never verified); a path outside
    the repo is named as such; --task and --path are one or the other."""
    repo, env = _repo(tmp_path)
    r = _okl(tmp_path, repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", "scoped-orders",
             "--title", "Order lookups are scoped to the signed-in customer", "--files", "src/orders.py",
             "--fix", "filter by the customer id from the session")
    assert r.returncode == 0, r.stderr

    for cwd, path in ((repo, "src/orders.py"), (repo, str(repo / "src" / "orders.py")), (repo / "src", "orders.py")):
        r = _okl(tmp_path, cwd, env, "check", "--path", path)
        assert r.returncode == 0, r.stderr
        assert "files: src/orders.py" in r.stdout and "[scoped-orders]" in r.stdout, (path, r.stdout)
        assert "UNVERIFIED" in r.stdout, r.stdout          # it governs files and has never been checked

    out = json.loads(_okl(tmp_path, repo, env, "check", "--path", "src/orders.py", "--path", "/etc/hosts",
                          "--format", "json").stdout)
    assert out["paths"] == ["src/orders.py"] and out["outside_repo"] == ["/etc/hosts"]
    assert [x["id"] for x in out["rules"]] == ["scoped-orders"]

    nothing = _okl(tmp_path, repo, env, "check", "--path", "README.md")
    assert nothing.returncode == 0 and "No lesson governs these files" in nothing.stdout
    assert _okl(tmp_path, repo, env, "check", "--path", "x", "--task", "y").returncode == 2
    assert _okl(tmp_path, repo, env, "check").returncode == 2


def test_a_service_answers_paths_and_an_older_one_is_refused(remote, monkeypatch):
    """Over a shared service the paths travel in the request; a service that answers without them
    (it predates #94) is refused, never read as "nothing governs this file". A request with neither
    a task nor paths is refused too."""
    _record(remote.store, "scoped-orders", "src/orders.py")
    result = Client().check("", paths=["src/orders.py"])
    assert result["paths"] == ["src/orders.py"] and [x["id"] for x in result["rules"]] == ["scoped-orders"]

    assert remote.api.post("/check", json={"repo": "r"}).status_code == 422

    real = Client._post
    monkeypatch.setattr(Client, "_post", lambda self, path, payload: {
        k: v for k, v in real(self, path, {**payload, "task": "orders"}).items() if k != "paths"})
    with pytest.raises(OKLRejectedError, match="answers `paths` on /check"):
        Client().check("", paths=["src/orders.py"])


def test_okl_check_mcp_tool_takes_a_path(tmp_path, monkeypatch):
    """The same question from any MCP agent: okl_check with `path` instead of `task`, and neither
    is answered with what to pass, not with a clean check."""
    pytest.importorskip("mcp")
    from okl.mcp_server import _build
    for k in ("OKL_SERVICE_URL", "OKL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir(); (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    _record(Store(f"sqlite:///{tmp_path / 'store.db'}"), "scoped-orders", "src/orders.py")

    def text(res):
        res = res[0] if isinstance(res, tuple) else res
        c = getattr(res, "content", res)
        c = c[0] if isinstance(c, list | tuple) else c
        return getattr(c, "text", str(c))

    async def exercise():
        mcp = _build()
        briefed = text(await mcp.call_tool("okl_check", {"path": ["src/orders.py"]}))
        assert "files: src/orders.py" in briefed and "[scoped-orders]" in briefed, briefed
        asked = text(await mcp.call_tool("okl_check", {}))
        assert asked.startswith("⚠️ okl_check needs a task, or a path"), asked

    asyncio.run(exercise())
