"""What an eval script needs to run a model or a check without the developer's setup leaking in.

Three read-only reviews of the harness (#446, 2026-11-14) found the same leaks in copies across
scripts, and a fix to one copy left the others as they were:
- model sessions started inside this checkout, where CLAUDE.md loads (§4ba, §4bb and §4bc's picker,
  screener and describer);
- children that inherit the launching Claude Code session's variables, its effort level among them
  (`xhigh` when §4bf ran), so an eval's effort followed whoever started it and no receipt said which;
- checks that kept `OKL_` and git-location variables, so a hook's `GIT_DIR` or a running warm model
  could answer for the scratch tree;
- replies taken from whichever model answered.

Each helper below closes one. New scripts use them instead of a copy of their own.

    env = sandbox.clean_env(tree=room)                      # a check's or an agent's environment
    with sandbox.empty_room() as room: ...                  # a model call that needs no files
    reply = sandbox.ask(argv, prompt, model="opus", effort="medium", timeout=300, cwd=room)
"""
from __future__ import annotations

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
# Dropped from every child: the launching session's own variables, okl's and git's. Kept: what
# signs the CLI in or names its provider, which an eval needs and which changes no answer.
DROP = ("CLAUDE", "OKL_", "GIT_", "MCP_")
KEEP = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def clean_env(tree: Path | None = None, **extra: str) -> dict[str, str]:
    """The environment for a child: none of the launching session's, okl's or git's variables;
    this interpreter's directory first on PATH; with `tree`, that tree's code first on PYTHONPATH.
    okl inside it logs no briefing and finds no warm model. `extra` sets more, explicitly."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(DROP) or k in KEEP}
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    env["OKL_BRIEFING_LOG"] = "0"
    env["OKL_WARM_SOCKET"] = str(Path(tempfile.gettempdir()) / "okl-eval-no-warm.sock")
    if tree is not None:
        env["PYTHONPATH"] = str(tree / "src")
    env.update(extra)
    return env


def inside_repo(path: Path) -> bool:
    """Whether `path` is this checkout or under it."""
    p, repo = path.resolve(), REPO.resolve()
    return p == repo or repo in p.parents


@contextmanager
def empty_room() -> Iterator[Path]:
    """A new empty directory outside the checkout, removed afterwards: where a model call that
    reads no files runs, so no CLAUDE.md, settings or memory of this project loads."""
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


def ask(argv: list[str], prompt: str, *, model: str, effort: str, timeout: int, cwd: Path) -> dict[str, Any]:
    """One headless session, run from `cwd` (never this checkout) with a clean environment and a
    pinned effort. Returns its text, cost, the models that answered, its turns and the effort, or
    an `error` when it timed out, gave no readable reply, failed, or was not answered by `model`
    (a usage limit looks like that). The caller records `models` and `effort` with each row."""
    if inside_repo(cwd):
        raise ValueError(f"a model call must not run inside the checkout ({cwd}): CLAUDE.md would load")
    cmd = with_effort(argv, effort)
    base = {"effort": effort, "models": [], "cost_usd": 0.0}
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           env=clean_env())
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


def copy_sqlite(src: Path, dst: Path) -> None:
    """A consistent copy of the SQLite database at `src`, with what its write-ahead log holds.
    Copying the file alone missed every write an open okl process had not checkpointed: the store
    runs in WAL mode, and the MCP server or a warm model can hold it open (#446). Read-only, so
    the copy never checkpoints or changes the original; where read-only access fails, the file and
    its log are copied together."""
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dst) as target:
            source.backup(target)
        source.close()
        target.close()
    except sqlite3.Error:
        dst.unlink(missing_ok=True)
        shutil.copy2(src, dst)
        for suffix in ("-wal", "-shm"):
            side = src.with_name(src.name + suffix)
            if side.exists():
                shutil.copy2(side, dst.with_name(dst.name + suffix))
