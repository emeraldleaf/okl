"""`okl on-edit`: run a lesson's check when the agent edits a file the lesson governs (#435).

A lesson can name the files it governs and carry the command that proves it, but the command
ran only when a person ran `okl verify` or `okl reverify`; the gates notice only that a governed
file changed. A lesson handed over alone changed the code where the same lesson in a list of ten
mostly did not (REPORT §4ax), and a failing check is not a list item. So after an edit, the
checks of the lessons governing the edited file run, and a failure goes straight back to the
agent beside its edit.

Only checks a person approved run. The commands come from the store, which on a shared service
holds records other people wrote, and stored data reaching a shell unasked is how a shared
store becomes remote code execution (lesson n_adea7f2c7373). So `okl on-edit add` shows each
command and asks, and the approval is the command's hash: a check whose stored command changes
afterwards is not run until it is approved again. The command runs through `okl verify`'s own
runner, the one place okl hands a confirmed command to a shell. Nothing here stamps a lesson
verified or blocks an edit: verification stays `okl verify`, on a commit.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .. import core
from ..client import Client, OKLUnreachableError, _find_config
from ..store import RETIRED_STATUSES
from .verification import _run_check, _stored_check

if TYPE_CHECKING:
    from ..store import Node

KEY = "on_edit"          # in .okl/config.json: {lesson id: approval hash}
TIMEOUT = 30             # seconds one check may take at edit time
BUDGET = 50              # seconds for every check one edit runs: Claude Code stops a hook at 60


def approval(run: str, expect: str | None) -> str:
    """What an approval pins: the exact command and the signal it must print."""
    return hashlib.sha256(f"{run}\0{expect or ''}".encode()).hexdigest()


def cmd_on_edit(args: argparse.Namespace) -> int:
    """List the approved edit-time checks, approve or drop some by id, or run the ones governing
    the files given. Exit 2 when there is no config here or the store cannot be read, an id
    cannot be approved, or approval was not given; `run` exits 1 when a check failed."""
    path = _find_config()
    if path is None:
        print("okl on-edit: no .okl/config.json here or above: run okl init first", file=sys.stderr)
        return 2
    config = json.loads(path.read_text())
    approved = {str(k): str(v) for k, v in (config.get(KEY) or {}).items()}
    client = Client()
    try:
        nodes = {n.id: n for n in client.all_nodes()}
    except OKLUnreachableError as e:
        print(f"okl on-edit: the store could not be read ({e})", file=sys.stderr)
        return 2
    args.action = args.action or "list"
    if args.action == "run":
        return _run(args, path.parent.parent, approved, nodes, client.repo)
    if args.action == "add":
        code = _add(args, approved, nodes, client.repo)
        if code:
            return code
    elif args.action == "remove":
        approved = {k: v for k, v in approved.items() if k not in set(args.targets)}
    if args.action in ("add", "remove") and approved != (config.get(KEY) or {}):
        if approved:
            config[KEY] = approved
        else:
            config.pop(KEY, None)
        path.write_text(json.dumps(config, indent=2) + "\n")
    _list(approved, nodes, client.repo)
    return 0


def _why_not(node: Node | None, repo: str) -> str | None:
    """Why a lesson cannot have an edit-time check, or None when it can."""
    if node is None:
        return "no lesson has this id"
    if node.status in RETIRED_STATUSES:
        return f"it is retired ({node.status})"
    if node.scope not in ("org", f"repo:{repo}"):
        return f"it belongs to another repository ({node.scope})"
    if not node.files:
        return "it governs no files, so no edit would run it: give it files with okl update --files"
    if _stored_check(node.verified_by) is None:
        return ("it has no stored check: prove it first with "
                f"okl verify {node.id} --run \"<check>\" --expect \"<signal>\"")
    return None


def _add(args: argparse.Namespace, approved: dict[str, str], nodes: dict[str, Node], repo: str) -> int | None:
    """Show each command and approve them on the person's yes, or --yes; None when approved."""
    wanted = list(dict.fromkeys(args.targets))
    if not wanted:
        print("okl on-edit add: name the lessons by id (okl on-edit lists the ones that can be added)",
              file=sys.stderr)
        return 2
    bad = [(i, why) for i in wanted if (why := _why_not(nodes.get(i), repo))]
    if bad:
        for i, why in bad:
            print(f"okl on-edit: cannot add [{i}]: {why}", file=sys.stderr)
        return 2
    # A refusal leaves stdout empty, so where it will refuse, the plan goes to stderr with it.
    asking = args.yes or sys.stdin.isatty()
    out = sys.stdout if asking else sys.stderr
    print("When the agent edits a file one of these lessons governs, okl will run its stored check, "
          "a command from the store, in this repository:", file=out)
    for i in wanted:
        run, expect = _stored_check(nodes[i].verified_by) or ("", None)
        print(f"  [{i}] {nodes[i].title}\n      files: {nodes[i].files}\n      runs:  {run}"
              + (f"\n      passes when its output contains {expect!r}" if expect else ""), file=out)
    if not asking:
        print("refusing to approve stored commands unattended: review them above, then pass --yes",
              file=sys.stderr)
        return 2
    if not args.yes and input("Approve them? [y/N] ").strip().lower() not in ("y", "yes"):
        print("okl on-edit: not approved; nothing changed", file=sys.stderr)
        return 2
    for i in wanted:
        approved[i] = approval(*(_stored_check(nodes[i].verified_by) or ("", None)))
    return None


def _list(approved: dict[str, str], nodes: dict[str, Node], repo: str) -> None:
    """The approved checks, each with whether it still runs, then the lessons that could be added."""
    if approved:
        print(f"{len(approved)} lesson check(s) run when the agent edits a file they govern:")
        for i, pinned in sorted(approved.items()):
            node = nodes.get(i)
            chk = _stored_check(node.verified_by) if node else None
            state = ("" if chk and approval(*chk) == pinned and _why_not(node, repo) is None
                     else "  (NOT RUN: " + (_why_not(node, repo) or "its stored check changed since it was "
                                             f"approved; review it with okl on-edit add {i}") + ")")
            print(f"  [{i}] {node.title if node else ''}{state}" + (f"\n      runs: {chk[0]}" if chk else ""))
    else:
        print("No lesson checks run on edit here. Approve the ones that are quick and need nothing but "
              "this checkout: okl on-edit add <id>...")
    can = sorted((n for n in nodes.values() if n.id not in approved and _why_not(n, repo) is None),
                 key=lambda n: n.id)
    if can:
        print(f"{len(can)} more could be added (they govern files and carry a stored check):")
        for n in can:
            print(f"  [{n.id}] {n.title}\n      runs: {(_stored_check(n.verified_by) or ('',))[0]}")


def _relative(paths: list[str], root: Path) -> set[str]:
    """The paths that lie inside the repository, repo-relative; others are dropped."""
    out = set()
    for p in paths:
        full = Path(p) if Path(p).is_absolute() else Path.cwd() / p
        with contextlib.suppress(ValueError, OSError):
            out.add(full.resolve().relative_to(root.resolve()).as_posix())
    return out


def _run(args: argparse.Namespace, root: Path, approved: dict[str, str], nodes: dict[str, Node], repo: str) -> int:
    """Run the approved checks of the lessons governing the edited files; report what failed."""
    rel = _relative(args.targets, root)
    hits = sorted((n for n in core.governing(list(nodes.values()), repo, rel) if n.id in approved),
                  key=lambda n: n.id) if rel else []
    failed: list[tuple[Node, str, str | None, str, str]] = []
    notes: list[str] = []
    passed = 0
    deadline = time.monotonic() + args.budget
    for n in hits:
        chk = _stored_check(n.verified_by)
        if chk is None or approval(*chk) != approved[n.id]:
            notes.append(f"[{n.id}] {n.title}: not run, because its stored check "
                         + ("is gone" if chk is None else "changed since it was approved")
                         + f"; the person can review it with okl on-edit add {n.id}")
            continue
        left = deadline - time.monotonic()
        if left <= 0:
            notes.append(f"[{n.id}] {n.title}: not run, out of time for this edit ({args.budget}s)")
            continue
        run, expect = chk
        timeout = max(1, min(args.timeout, math.ceil(left)))
        said = io.StringIO()
        here = Path.cwd()
        try:
            os.chdir(root)
            with contextlib.redirect_stderr(said):
                output, outcome = _run_check(argparse.Namespace(run=run, expect=expect, timeout=timeout))
        finally:
            os.chdir(here)
        if output is not None:
            passed += 1
        elif outcome.startswith("timed out"):
            notes.append(f"[{n.id}] {n.title}: its check did not finish in {timeout}s, so it was not judged")
        else:
            failed.append((n, run, expect, outcome, said.getvalue()))
    text = _report(sorted(rel), failed, notes)
    if args.format == "hook":
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    else:
        print(text or (f"okl on-edit: {passed} approved check(s) passed for {', '.join(sorted(rel))}"
                       if hits else f"okl on-edit: no approved check governs {', '.join(sorted(rel)) or 'these files'}"))
    return 1 if failed else 0


def _report(paths: list[str], failed: list, notes: list[str]) -> str:
    """What the agent is told: each failing lesson with its fix, the command and the end of its
    output, then anything not run. Empty when every check passed."""
    lines: list[str] = []
    if failed:
        lines.append(f"OKL CHECK FAILED after editing {', '.join(paths)}: a lesson that governs this file "
                     "carries a check, and the check fails now.")
        for n, run, expect, outcome, said in failed:
            fix = " ".join((n.fix or "").split())
            lines.append(f"- [{n.id}] {n.title}")
            if fix:
                lines.append(f"  fix: {fix[:400]}")
            lines.append(f"  check: {run}" + (f"  (passes when its output contains {expect!r})" if expect else ""))
            tail = [ln for ln in said.splitlines()[1:] if ln.strip()]
            lines.append(f"  result: {outcome}" + (": the last lines it printed:" if tail else ""))
            lines.extend(f"    {ln}" for ln in tail)
        lines.append("Fix the code so the check passes, and run it again yourself to see. If the lesson itself "
                     "is out of date, say so to the person rather than changing the check. okl recorded nothing.")
    if notes:
        lines.append("OKL: some checks for this edit were not run:" if not failed else "Also not run:")
        lines.extend(f"- {s}" for s in notes)
    return "\n".join(lines)
