#!/usr/bin/env python3
"""The README's `okl check` defaults hold on every path a check takes.

The check behind the `doc-check-defaults` rule. The README says a check draws on 12 lessons
unless `--limit` says otherwise, and documents every `--format`. The 12 is set in four places:
core.check's default, the service's request body, and the CLI and the client, which must pass
no limit of their own so the store or the service applies it. The first version read core.check
alone, so a break that set the client's limit to 10 or the service's to 8 passed it (REPORT §4af,
#318). The service is read from its source, so this runs without the service extra.
"""
import ast
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from okl import client, core  # noqa: E402
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

# The client, asked for no limit, must leave it to the store: what reaches core.check.
seen: dict = {}
core.check = lambda _store, _repo, _task, **kw: seen.update(kw) or {}
client.drift.annotate_briefing = lambda *a, **k: None
c = client.Client(config={"repo": "r"})
c._local_store = lambda: None
c.check("a task")
if seen.get("limit", LIMIT) != LIMIT:
    problems.append(f"the client sends a limit of {seen['limit']} when none is asked for")

help_text = subprocess.run([sys.executable, "-m", "okl", "check", "--help"], capture_output=True, text=True,
                           cwd=REPO, check=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")}).stdout
formats = re.search(r"--format \{([a-z,]+)\}", help_text).group(1).split(",")
readme = (REPO / "README.md").read_text()
if f"--limit {LIMIT}" not in readme:
    problems.append(f"the README does not state --limit {LIMIT}")
problems += [f"the README does not document --format {f}" for f in formats if f != "agent" and f"--format {f}" not in readme]

if problems:
    sys.exit("CHECK DEFAULTS DIFFER: " + "; ".join(problems))
print("CHECK DEFAULTS MATCH", formats)  # noqa: T201 - a check script reports on stdout
