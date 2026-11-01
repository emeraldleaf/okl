#!/usr/bin/env python3
"""The README's `okl check` defaults hold on every path a check takes.

The check behind the `doc-check-defaults` rule. The README says a check names up to twelve
records unless `--limit` says otherwise, and documents every `--format`. The 12 is set in
core.check and in the service's request body; the CLI, its handler, the client (local and
remote) and the MCP tool must pass no limit of their own, so the store or the service applies
it. Each path is run with what lies past it stubbed, and the stub must be reached. The first
version read core.check alone, so a break that set the client's limit to 10 or the service's to
8 passed it (REPORT §4af, #318). The service and the MCP tool are read from their source, so
this runs without their extras.
"""
import ast
import contextlib
import inspect
import io
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from okl import client, core  # noqa: E402
from okl.cli import lessons, main  # noqa: E402
from okl.cli.parser import build_parser  # noqa: E402

LIMIT = 12
problems = []

if inspect.signature(core.check).parameters["limit"].default != LIMIT:
    problems.append(f"core.check's limit is {inspect.signature(core.check).parameters['limit'].default}")

tree = ast.parse((REPO / "src/okl/service.py").read_text())
request = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "CheckReq")
field = next(n for n in request.body if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "limit")
if not (isinstance(field.value, ast.Constant) and field.value.value == LIMIT):
    problems.append(f"the service's CheckReq.limit is {ast.unparse(field.value) if field.value else 'unset'}")

check_cmd = build_parser()._subparsers._group_actions[0].choices["check"]
cli_limit = next(a.default for a in check_cmd._actions if "--limit" in a.option_strings)
if cli_limit not in (None, LIMIT):
    problems.append(f"`okl check --limit` defaults to {cli_limit}")

tree = ast.parse((REPO / "src/okl/mcp_server.py").read_text())
tool = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "okl_check")
names = [a.arg for a in tool.args.args]
default = tool.args.defaults[names.index("limit") - (len(names) - len(tool.args.defaults))]
if not (isinstance(default, ast.Constant) and default.value in (None, LIMIT)):
    problems.append(f"the MCP tool's limit defaults to {ast.unparse(default)}")


class _Asked:
    """A client for the CLI handler: records the limit it is asked for."""
    configured, seen = True, None

    def check(self, _task: str, repo: str | None = None, limit: object = "unset") -> dict:
        _Asked.seen = limit
        return {}


lessons.Client = _Asked
with contextlib.redirect_stdout(io.StringIO()):
    main(["check", "--task", "a task", "--format", "json"])
if _Asked.seen not in (None, LIMIT):
    problems.append(f"`okl check` asks the client for a limit of {_Asked.seen}" if _Asked.seen != "unset"
                    else "`okl check` never asked the client for a briefing")

# The client, asked for no limit, must leave it to the store or the service: what reaches them.
seen: dict = {}
core.check = lambda _store, _repo, _task, **kw: seen.setdefault("local", kw) and {} or {}
client.drift.annotate_briefing = lambda *a, **k: None
local = client.Client(config={"repo": "r"})
local._local_store = lambda: None
local.check("a task")
remote = client.Client(config={"repo": "r", "service_url": "http://okl.invalid"})
remote._post_check = lambda payload: seen.setdefault("remote", payload) and {} or {}
remote.check("a task")
for path in ("local", "remote"):
    if path not in seen:
        problems.append(f"the {path} client never reached the store or the service")
    elif seen[path].get("limit", LIMIT) != LIMIT:
        problems.append(f"the {path} client sends a limit of {seen[path]['limit']} when none is asked for")

help_text = subprocess.run([sys.executable, "-m", "okl", "check", "--help"], capture_output=True, text=True,
                           cwd=REPO, check=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")}).stdout
formats = re.search(r"--format \{([a-z,]+)\}", help_text).group(1).split(",")
readme = (REPO / "README.md").read_text()
if "up to twelve" not in " ".join(readme.split()):
    problems.append("the README does not say a check names up to twelve records")
problems += [f"the README does not document --format {f}" for f in formats if f != "agent" and f"--format {f}" not in readme]

if problems:
    sys.exit("CHECK DEFAULTS DIFFER: " + "; ".join(problems))
print("CHECK DEFAULTS MATCH", formats)  # noqa: T201 - a check script reports on stdout
