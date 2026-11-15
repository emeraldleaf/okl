"""What an eval script needs to run a model or a check without the developer's setup leaking in.

Three read-only reviews of the harness (#446, 2026-11-14) found the same leaks in copies across
scripts, and a fix to one copy left the others as they were:
- model sessions started inside a git tree of this repository, which read its git status: the branch,
  the last five commit subjects and changed, deleted and untracked file names (§4ba–§4bc's pickers; the
  breakers of §4af, §4ah and §4bf, whose status named the check files hidden from them);
- children that inherit the launching Claude Code session's variables, okl's and git's, and calls made
  without --restricted that take their effort from the user's settings file, which no receipt recorded;
- checks that kept `OKL_` and git-location variables, so a hook's `GIT_DIR` or a running warm model
  could answer for the scratch tree;
- replies taken from whichever model answered.

Each helper below closes one. New scripts use them instead of a copy of their own.

    env = sandbox.clean_env(tree=room)                      # a check's or an agent's environment
    with sandbox.empty_room() as room: ...                  # a model call that needs no files
    reply = sandbox.ask(argv, prompt, model="opus", effort="medium", timeout=300, cwd=room)
    with sandbox.no_git(tree): ...                          # a session that must work in a repo tree
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
_RUN = subprocess.run   # git's own answer for inside_repo, even where a test stands in for the model call
# Dropped from every child: the launching session's own variables, okl's and git's, and the ones that
# choose a model or a thinking budget behind the alias a script names. Kept: what signs the CLI in and
# selects its provider (every CLAUDE_CODE_USE_ selector), which an eval needs and which changes no answer.
# A call made without --restricted still reads the user's settings file, its effort and model settings
# included (#446): pass --restricted, or pin the effort with ask(effort=...).
DROP = ("CLAUDE", "OKL_", "GIT_", "MCP_", "ANTHROPIC_DEFAULT_")
DROP_EXACT = frozenset({"ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "MAX_THINKING_TOKENS"})
# Exact names: the provider selectors this CLI reads (from its own strings, 2.1.302), so no other
# CLAUDE_CODE_USE_ switch, such as a tool or a search mode, rides along.
KEEP = frozenset({"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                  "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
                  "CLAUDE_CODE_USE_GATEWAY", "CLAUDE_CODE_USE_MANTLE"})
# A receipt field: the script's children ran in clean_env. Written only when clean_env was called in
# this process (USED), never as a blanket default (review on #451); the lint in
# tests/test_harness_fixes.py holds every model call in evals/ to it.
MODEL_ENV = "sandbox.clean_env (#446)"
USED = False
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def clean_env(tree: Path | None = None, **extra: str) -> dict[str, str]:
    """The environment for a child: none of the launching session's, okl's or git's variables;
    this interpreter's directory first on PATH; with `tree`, that tree's code first on PYTHONPATH.
    okl inside it logs no briefing, and neither finds nor starts a warm model: with warm on, a check that
    finds none starts one at the socket, where it would outlive the run. `extra` sets more, explicitly."""
    global USED
    USED = True
    env = {k: v for k, v in os.environ.items() if k in KEEP or not (k.startswith(DROP) or k in DROP_EXACT)}
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    env["OKL_BRIEFING_LOG"] = "0"
    env["OKL_WARM"] = "0"
    env["OKL_WARM_SOCKET"] = str(Path(tempfile.gettempdir()) / "okl-eval-no-warm.sock")
    if tree is not None:
        env["PYTHONPATH"] = str(tree / "src")
    env.update(extra)
    return env


def inside_repo(path: Path) -> bool:
    """Whether `path` is this checkout or under it, or in any git worktree of this repository: a
    session in either reads this repository's git status."""
    p, repo = path.resolve(), REPO.resolve()
    if p == repo or repo in p.parents:
        return True
    def common_dir(at: Path) -> Path | None:
        # No --path-format: git before 2.31 echoes it back as output. A relative answer is relative to `at`.
        # Without the launcher's GIT_DIR and friends: they would point both probes at one repository.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        got = _RUN(["git", "-C", str(at), "rev-parse", "--git-common-dir"], capture_output=True, text=True, env=env)
        out = got.stdout.strip()
        return (at / out).resolve() if got.returncode == 0 and out else None
    theirs = common_dir(p)
    return theirs is not None and theirs == common_dir(repo)


@contextmanager
def empty_room() -> Iterator[Path]:
    """A new empty directory outside the checkout, removed afterwards: where a model call that
    reads no files runs, outside any git tree, so no git status of this repository loads."""
    with tempfile.TemporaryDirectory(prefix="okl-eval-room-") as d:
        yield Path(d)


def with_effort(argv: list[str], effort: str) -> list[str]:
    """`argv` with `--effort` pinned right after `claude -p`. It cannot go last: `--allowedTools`
    takes the rest of the line."""
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {EFFORTS}, not {effort!r}")
    if argv[:2] != ["claude", "-p"]:
        raise ValueError(f"not a headless claude call: {argv[:2]}")
    if "--effort" in argv:
        raise ValueError("argv already names an effort; pass it as `effort=`")
    return [*argv[:2], "--effort", effort, *argv[2:]]


def ask(argv: list[str], prompt: str, *, model: str, effort: str, timeout: int, cwd: Path,
        tree: Path | None = None, unset: tuple[str, ...] = ()) -> dict[str, Any]:
    """One headless session, run from `cwd` (never this checkout) with a clean environment and a
    pinned effort. Returns its text, cost, the models that answered, its turns and the effort, or
    an `error` when it timed out, gave no readable reply, failed, or was not answered by `model`
    (a usage limit looks like that). The caller records `models` and `effort` with each row.

    `tree` puts that copy's code first on PYTHONPATH, for an agent that runs the copy's tests: without
    it they import whichever okl the interpreter finds. `unset` leaves out variables clean_env sets, for
    an agent whose task is the behaviour one of them turns off (OKL_BRIEFING_LOG, for a defect in what
    gets logged): only in a copy with no store of this checkout's to log into."""
    if inside_repo(cwd):
        raise ValueError(f"a model call must not run inside the checkout ({cwd}): it would read this repository's "
                         "git status, commit subjects included")
    if tree is not None and inside_repo(tree):
        raise ValueError(f"tree {tree} is inside the checkout")
    cmd = with_effort(argv, effort)
    base = {"effort": effort, "models": [], "cost_usd": 0.0}
    env = clean_env(tree=tree)
    for name in unset:
        env.pop(name, None)
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           env=env)
    except subprocess.TimeoutExpired:
        return {**base, "error": f"timed out after {timeout}s"}
    try:
        envelope = json.loads(p.stdout)
    except ValueError:
        return {**base, "error": (p.stderr or p.stdout or f"exit {p.returncode}, no output")[-300:]}
    models = sorted(envelope.get("modelUsage") or {})
    out = {**base, "result": envelope.get("result") or "", "models": models,
           "cost_usd": envelope.get("total_cost_usd") or 0.0, "turns": envelope.get("num_turns")}
    if envelope.get("is_error"):
        return {**out, "error": out["result"][-300:] or "the session reported an error"}
    if not any(model in m for m in models):
        return {**out, "error": f"answered by {models}, not {model}"}
    return out


def connect(target: str | Path, uri: bool = False) -> sqlite3.Connection:
    """The one place this module opens a database: an adapter okl owns, so a test watches it rather than
    faking sqlite3 (lesson py_dont_mock_what_you_dont_own)."""
    return sqlite3.connect(target, uri=uri)


def copy_sqlite(src: Path, dst: Path, *, allow_file_copy: bool = False) -> None:
    """A consistent copy of the SQLite database at `src`, with what its write-ahead log holds.
    Copying the file alone missed every write an open okl process had not checkpointed: the store
    runs in WAL mode, and the MCP server or a warm model can hold it open (#446). Opened read-only,
    so the copy never checkpoints into the original or changes its rows; on a WAL database with no log
    on disk, SQLite may still create the empty -wal and -shm files beside it. Where read-only access
    fails it raises, unless `allow_file_copy`: copying the file and then its log is not atomic, since a
    checkpoint between the two copies would mismatch them (review on #451)."""
    uri = Path(src).resolve().as_uri() + "?mode=ro"   # escaped: a "?" in a folder name cut the old path
    try:
        with contextlib.closing(connect(uri, uri=True)) as source, contextlib.closing(connect(dst)) as target:
            source.backup(target)
    except sqlite3.Error as e:
        if not allow_file_copy:
            raise RuntimeError(f"read-only copy of {src} failed ({e}); not copying the file and its log apart") from e
        print(f"sandbox: read-only copy of {src} failed ({e}); copying the file and its log instead",
              file=sys.stderr)
        dst.unlink(missing_ok=True)
        shutil.copy2(src, dst)
        log = src.with_name(src.name + "-wal")
        if log.exists():
            shutil.copy2(log, dst.with_name(dst.name + "-wal"))


def settings_effort() -> dict[str, Any] | None:
    """The effort levels the user's settings file sets, which a call made without --restricted reads: the
    default, and any per-model level, which wins for its model. A receipt records them beside the
    commands it ran (#446)."""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        d = json.loads((base / "settings.json").read_text())
    except (OSError, ValueError):
        return None
    per = {m: v.get("effortLevel") for m, v in (d.get("modelSettings") or {}).items()
           if isinstance(v, dict) and isinstance(v.get("effortLevel"), str)}
    level = d.get("effortLevel") if isinstance(d.get("effortLevel"), str) else None
    return {"effortLevel": level, "modelSettings": per} if level or per else None


@contextlib.contextmanager
def no_git(tree: Path) -> Iterator[None]:
    """`tree` without its link to the repository while a model session works in it. A session in a git
    tree reads its status into context: §4bf's breakers saw the branch, the last five commit subjects
    (which named the experiment) and the check files hidden from them, listed as deleted (#446). The
    link is kept outside the tree, under a name that says nothing, and restored on every way out."""
    link = tree / ".git"
    kept = tree.parent / f".{tree.name}.link"
    link.rename(kept)
    try:
        yield
    finally:
        kept.rename(link)
