"""`okl check --path`: the lessons that govern a file, asked before it is read or edited (#94)."""
import asyncio
import json
import os
import shutil
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
    if shutil.which("git") is None:
        pytest.skip("git not available")
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


@pytest.mark.parametrize("entry", [
    "src/orders.py", "src", "src/", "src/*.py", "*.py", "src/*/x.py",
    ":(glob)src/**/*.py", ":(glob)src/*.py", ":(glob)**/x.py", ":(glob)src/**",
    ":(literal)src/*.py", ":(icase)SRC/Orders.py", ":/src/orders.py", ":(top)docs",
])
def test_path_matching_agrees_with_git(tmp_path, entry):
    """A lesson's `files` entry covers the same paths for the briefing by file as for drift's
    `git log`: compared here with git's own pathspec, default and magic (CLI review on #362)."""
    from okl.store import path_matches
    if shutil.which("git") is None:
        pytest.skip("git not available")
    files = ["src/orders.py", "src/a/x.py", "src/a/b/c.py", "src/*.py", "x.py", "docs/README.md", "src/orders.pyc"]
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True); (tmp_path / f).write_text("x\n")
    local = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
    env = {k: v for k, v in os.environ.items() if k not in local}
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True, env=env)
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", *[f":(literal){f}" for f in files]], check=True, env=env)
    by_git = set(subprocess.run(["git", "-C", str(tmp_path), "ls-files", "--", entry], capture_output=True,
                                text=True, check=True, env=env).stdout.split())
    assert {f for f in files if path_matches(entry, f)} == by_git, entry


def test_other_pathspec_magic_matches_nothing():
    """`:(exclude)` and the like are never guessed at: no match, rather than a wrong one."""
    from okl.store import path_matches
    assert not path_matches(":(exclude)src", "src/orders.py")
    assert not path_matches(":(attr:x)src", "src/orders.py")


def test_a_symlinked_file_keeps_its_own_name(tmp_path, monkeypatch):
    """A tracked symlink is governed by its own path, as git tracks it, not by its target's; `..`
    and `.` still fold (CLI review on #362)."""
    from okl.client import _repo_relative
    (tmp_path / "src").mkdir(); (tmp_path / "src" / "impl.py").write_text("x\n")
    (tmp_path / "src" / "current.py").symlink_to("impl.py")
    monkeypatch.chdir(tmp_path / "src")
    inside, outside = _repo_relative([str(tmp_path / "src" / "current.py"), "../src/./current.py", "../../elsewhere.py"],
                                     tmp_path)
    assert inside == ["src/current.py", "src/current.py"] and outside == ["../../elsewhere.py"]


def test_a_file_briefing_is_never_cut_and_an_empty_request_is_no_check(remote):
    """`limit` caps a task's briefing, never the lessons that govern a file: compact and limited,
    every one is still shown. And no paths at all is refused, by the client and the service, not
    answered as a clean check (CLI review on #362)."""
    for i in range(4):
        _record(remote.store, f"rule-{i}", "src/orders.py")
    result = core.check_paths(remote.store, "r", ["src/orders.py"])
    shown = core.render_actions_only(result, limit=2)
    assert shown.startswith("OKL — 4 rule(s) govern") and all(f"rule-{i}" in shown for i in range(4)), shown

    with pytest.raises(ValueError, match="no paths given"):
        Client().check("", paths=[])
    assert remote.api.post("/check", json={"repo": "r", "paths": []}).status_code == 422


READ_HOOK = ROOT / "src" / "okl" / "scaffold" / "hooks" / "posttooluse-okl-read.sh"


def _read_hook(repo, env, tmp_path, file_path, session="s1", **extra):
    hook_env = {**env, "CLAUDE_PROJECT_DIR": str(repo), "OKL_BIN": f"{sys.executable} -m okl",
                "OKL_DATABASE_URL": f"sqlite:///{tmp_path / 'store.db'}", "PYTHONPATH": str(ROOT / "src"),
                "TMPDIR": str(tmp_path), "OKL_FRAME_LOG": str(tmp_path / "frames.jsonl"), **extra}
    hook_env.pop("OKL_SERVICE_URL", None)
    stdin = json.dumps({"session_id": session, "hook_event_name": "PostToolUse", "tool_name": "Read",
                        "tool_input": {"file_path": file_path}})
    return subprocess.run(["bash", str(READ_HOOK)], cwd=repo, env=hook_env, input=stdin,
                          capture_output=True, text=True)


def test_the_read_hook_briefs_a_files_lessons_once_framed_and_never_silently_fails(tmp_path):
    """After a Read, the hook returns the lessons governing the file as PostToolUse
    additionalContext, framed by their sha256 and byte count and logged the same (REPORT §4aj);
    the same session's next read of it is quiet unless drift marks a lesson (this one, never
    verified, stays marked); an ungoverned file gets nothing; okl failing is said, not silent."""
    import hashlib
    repo, env = _repo(tmp_path)
    r = _okl(tmp_path, repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", "ledger-audit",
             "--title", "Every ledger read goes through the audit trail", "--files", "src/orders.py",
             "--fix", "call audit_trail_7Q(account_id) before returning entries")
    assert r.returncode == 0, r.stderr

    first = _read_hook(repo, env, tmp_path, str(repo / "src" / "orders.py"))
    assert first.returncode == 0, first.stderr
    out = json.loads(first.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    frame, body = out["additionalContext"].split("\n", 1)
    digest = hashlib.sha256(body.encode()).hexdigest()
    assert frame == f"okl-briefing sha256={digest} bytes={len(body.encode())}"
    assert "audit_trail_7Q" in body and "[ledger-audit]" in body
    logged = [json.loads(x) for x in (tmp_path / "frames.jsonl").read_text().splitlines()]
    assert logged[-1]["sha256"] == digest and logged[-1]["session"] == "s1"

    # never verified, so drift marks it, and it is briefed again; once verified it would be quiet
    again = _read_hook(repo, env, tmp_path, str(repo / "src" / "orders.py"))
    assert "audit_trail_7Q" in again.stdout

    assert _read_hook(repo, env, tmp_path, str(repo / "README.md")).stdout == ""
    assert _read_hook(repo, env, tmp_path, str(repo / "src" / "orders.py"),
                      OKL_DISABLED_HOOKS="read").stdout == ""
    broken = _read_hook(repo, env, tmp_path, str(repo / "src" / "orders.py"), OKL_BIN="/no/such/okl",
                        PATH="/usr/bin:/bin", PYTHONPATH="/nowhere")
    note = json.loads(broken.stdout)["hookSpecificOutput"]["additionalContext"]
    assert broken.returncode == 0 and note.startswith("OKL NOT BRIEFED for ") and "cannot see" in note


def test_once_per_session_drops_a_lesson_already_briefed_unless_drift_marks_it(tmp_path, monkeypatch):
    """The dedupe itself: a verified lesson briefed once in a session is left out of that session's
    next file briefing, and a drift-marked one is kept; another session starts afresh."""
    from okl.cli.lessons import _once_per_session
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    def result():
        return {"rules": [{"id": "proven"}, {"id": "stale", "drift": {"reason": "changed"}}],
                "next_actions": [{"id": "proven"}, {"id": "stale", "drift": {"reason": "changed"}}],
                "match_count": 2}
    first = result(); _once_per_session(first, "s1")
    assert [r["id"] for r in first["rules"]] == ["proven", "stale"]
    second = result(); _once_per_session(second, "s1")
    assert [r["id"] for r in second["rules"]] == ["stale"] and second["match_count"] == 1
    other = result(); _once_per_session(other, "s2")
    assert [r["id"] for r in other["rules"]] == ["proven", "stale"]


def test_the_e2e_instrument_builds_measures_and_summarizes_without_a_session(tmp_path, monkeypatch):
    """REPORT §4aj's plumbing, with no model: a treatment repo whose hook, fired as Claude Code
    would after a Read, logs a frame; `measure` finds the read, the frame and the canary in a
    transcript; `summarize` reads the registered predictions. The control repo registers no hook."""
    import importlib.util
    if shutil.which("git") is None:
        pytest.skip("git not available")
    spec = importlib.util.spec_from_file_location("e2e_read_briefing", ROOT / "evals" / "e2e_read_briefing.py")
    e2e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e2e)

    room = tmp_path / "t"; room.mkdir()
    repo, env = e2e.build(room, "treatment")
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["PostToolUse"][0]["matcher"] == "Read"
    stdin = json.dumps({"session_id": "sess-1", "tool_name": "Read",
                        "tool_input": {"file_path": str(repo / "src" / "ledger.py")}})
    hook = subprocess.run(["bash", str(repo / ".claude" / "hooks" / e2e.HOOK.name)], cwd=repo, input=stdin,
                          env={**env, "CLAUDE_PROJECT_DIR": str(repo)}, capture_output=True, text=True)
    context = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
    assert e2e.CANARY in context

    # A transcript as Claude Code writes one: the Read, then the hook's context beside its result.
    projects = tmp_path / "home" / ".claude" / "projects" / "x"; projects.mkdir(parents=True)
    (projects / "sess-1.jsonl").write_text("\n".join(json.dumps(x) for x in (
        {"message": {"content": [{"type": "tool_use", "name": "Read",
                                  "input": {"file_path": str(repo / "src" / "ledger.py")}}]}},
        {"message": {"content": [{"type": "text", "text": context}]}})) + "\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (repo / "src" / "ledger.py").write_text(e2e.FIXTURE + f"\n\ndef entries_for(a):\n    {e2e.CANARY}(a)\n")
    got = e2e.measure(repo, room, {"session_id": "sess-1"})
    assert got["read"] and got["arrived"] and got["used"] and got["defines_entries_for"]

    croom = tmp_path / "c"; croom.mkdir()
    crepo, _ = e2e.build(croom, "control")
    assert json.loads((crepo / ".claude" / "settings.json").read_text()) == {}
    summary = e2e.summarize([{"arm": "treatment", **got}, {"arm": "control", "read": True, "used": False,
                                                           "frames": [], "arrived": False}])
    assert summary["treatment"] == {"runs": 1, "read": 1, "arrived": 1, "used": 1}
    assert summary["predictions"]["1_arrives_in_every_treatment_read"]
    assert summary["predictions"]["3_no_control_uses_canary"] and not summary["counts_only"]


def test_the_replies_receipt_counts_the_reasons_by_fixed_patterns(tmp_path):
    """§4aj's exploratory counts come from a committed receipt: each treatment agent's final reply
    verbatim, and each reason found by a fixed pattern (the CI review's must-fix on #363)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("e2e_read_briefing", ROOT / "evals" / "e2e_read_briefing.py")
    e2e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e2e)
    replies = {"s1": "I left out audit_trail_7Q(account_id): you didn't ask for it and there's no `audit` module.",
               "s2": "I looked for audit.py and neither exists, so audit_trail_7Q would raise an ImportError. "
                     "The briefing marks it unverified."}
    for sid, text in replies.items():
        room = tmp_path / f"okl-e2e-treatment-{sid}"; room.mkdir()
        (room / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in (
            {"sessionId": sid, "type": "user"},
            {"sessionId": sid, "message": {"role": "assistant", "content": [{"type": "text", "text": "Reading."}]}},
            {"sessionId": sid, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})) + "\n")
    receipt = tmp_path / "e2e-read-briefing-x.json"
    receipt.write_text(json.dumps({"transcripts_kept_in": str(tmp_path), "runs": [
        {"arm": "treatment", "session": "s1"}, {"arm": "control", "session": "c1"},
        {"arm": "treatment", "session": "s2"}]}))
    out = json.loads(e2e.replies(receipt).read_text())
    assert out["of"] == 2 and [r["final_reply"] for r in out["replies"]] == [replies["s1"], replies["s2"]]
    assert out["counts"] == {"names_the_canary": 2, "module_missing": 2, "not_asked": 1, "marked_unverified": 1}
