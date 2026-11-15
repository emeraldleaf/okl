"""`okl on-edit`: run the approved lessons' checks after the agent edits a file in the repository
(#435, #450), those governing the edited file first.

A lesson can name the files it governs and carry the command that proves it, but the command
ran only when a person ran `okl verify` or `okl reverify`; the gates notice only that a governed
file changed. A lesson handed over alone changed the code where the same lesson in a list of ten
mostly did not (REPORT §4ax), and a failing check is not a list item. So after an edit, the
approved checks run, those of the lessons governing the edited file first, and a failure goes
straight back to the agent beside its edit.

Only checks a person approved run. The commands come from the store, which on a shared service
holds records other people wrote, and stored data reaching a shell unasked is how a shared
store becomes remote code execution (lesson n_adea7f2c7373). So `okl on-edit add` shows each
command and asks, and the approval is the command's hash: a check whose stored command changes
afterwards is not run until it is approved again. The command runs through `okl verify`'s own
runner, the one place okl hands a confirmed command to a shell. Nothing here stamps a lesson
verified or blocks an edit: verification stays `okl verify`, on a commit.

A lesson's files say where it was found, not everywhere it holds. A lesson whose check CI already
runs is given none (#39), many rules hold wherever code does what they are about, and a lesson tied
to one file can be broken in another its files never name (#450). Tied to files only, the hook would
have run a check for 4 of REPORT §4bf's 61 confirmed breaks. So every approved check runs after any
edit inside the repository: those of the lessons governing the edited file first, since the budget
is spent in order, then the rest. Files decide the order, and drift; never whether a check runs.
For a check CI runs, this changes when a break is found, at the edit rather than at the push, not
whether.

Which checks are quick enough to run after every edit is the person's call, made from each check's
time (#467): `okl verify` and `okl reverify` log how long each run took, and `okl on-edit add
--quick` offers the lessons whose stored check last passed in at most `--under` seconds, each shown
and approved on one yes, pinned as one named by id is. A check never timed is listed apart and never
offered: its time is unknown, not short, and `okl reverify --untimed` re-runs such checks once, on
the person's yes, to time them. Runs here are neither logged nor timed, so an edit never
adds to the check log: `okl recap` counts a logged run as a stale lesson re-checked, and changing
what counts there is not this command's to do.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .. import core
from ..client import Client, OKLUnreachableError, _find_config, _repo_relative, save_config
from ..store import RETIRED_STATUSES
from .verification import _run_check, _stored_check, shown

if TYPE_CHECKING:
    from ..store import Node

KEY = "on_edit"          # in .okl/config.json: {lesson id: approval hash}
TIMEOUT = 30             # seconds one check may take at edit time
BUDGET = 50              # seconds for every check one edit runs, from okl's start
HOOK_TIMEOUT = 60        # seconds okl registers the edit hook with, so Claude Code stops it there
QUICK = 10               # seconds: `okl on-edit add --quick` offers the checks whose last pass took at most this


def approval(run: str, expect: str | None) -> str:
    """What an approval pins: the exact command and the signal it must print, as one JSON
    pair, so no command and signal can be rearranged into another with the same hash."""
    return hashlib.sha256(json.dumps([run, expect or ""]).encode()).hexdigest()


def cmd_on_edit(args: argparse.Namespace) -> int:
    """List the approved edit-time checks, approve or drop some by id, or run them after an edit to
    the files given. Exit 2 when there is no config here or the store cannot be read, an id
    cannot be approved, or approval was not given; `run` exits 1 when a check failed."""
    started = time.monotonic()
    try:
        return _on_edit(args, started)
    # A crash exits 1 with nothing on stdout, which the hook and any caller read as a finding with
    # nothing to say, and the approved checks then never ran unnoticed (a corrupt store, a
    # malformed config: review of #441). Anything unforeseen is a could-not-run.
    except Exception as e:  # noqa: BLE001 - see above
        print(f"okl on-edit: could not run: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


def _on_edit(args: argparse.Namespace, started: float) -> int:
    path = _find_config()
    if path is None:
        print("okl on-edit: no .okl/config.json here or above: run okl init first", file=sys.stderr)
        return 2
    config = json.loads(path.read_text())
    raw = config.get(KEY) or {}
    if not isinstance(raw, dict):
        print(f"okl on-edit: `{KEY}` in {path} must map lesson ids to approvals; fix or remove it",
              file=sys.stderr)
        return 2
    approved = {str(k): str(v) for k, v in raw.items()}
    client = Client()
    try:
        nodes = {n.id: n for n in client.all_nodes()}
    except OKLUnreachableError as e:
        print(f"okl on-edit: the store could not be read ({e})", file=sys.stderr)
        return 2
    args.action = args.action or "list"
    if args.action == "run":
        return _run(args, path.parent.parent, approved, nodes, client.repo, started=started)
    change = {"add": _add, "remove": _remove}.get(args.action)
    code = change(args, approved, nodes, client) if change else None
    if code:
        return code
    if change and approved != (config.get(KEY) or {}):
        if approved:
            config[KEY] = approved
        else:
            config.pop(KEY, None)
        save_config(config, path.parent.parent)
    _list(approved, nodes, client)
    return 0


def _why_not(node: Node | None, repo: str) -> str | None:
    """Why a lesson cannot have an edit-time check, or None when it can: the first reason that
    holds, in order."""
    if node is None:
        return "no lesson has this id"
    check = _stored_check(node.verified_by)
    hidden = check is not None and not all(
        s.isprintable() for s in (check[0], check[1] or "", node.title, node.files or ""))
    reasons = (
        (node.status in RETIRED_STATUSES, f"it is retired ({node.status})"),
        (node.scope not in ("org", f"repo:{repo}"), f"it belongs to another repository ({shown(node.scope)})"),
        (check is None, "it has no stored check: prove it first with "
                        f"okl verify {shown(node.id)} --run \"<check>\" --expect \"<signal>\""),
        # What the person approves must be what runs: a control code, a zero-width or a direction
        # mark can show one command over another (review of #441; issue #185).
        (hidden, "its command, signal, title or files hold a control, format or separator character "
                 "(an escape code, a zero-width or a direction mark, a line break), which a terminal "
                 "can use to show one command over another, so it cannot be approved: fix the lesson "
                 "first"),
    )
    return next((why for bad, why in reasons if bad), None)


def _add(args: argparse.Namespace, approved: dict[str, str], nodes: dict[str, Node], client: Client) -> int | None:
    """Show each command and approve them on the person's yes, or --yes; None when approved. With
    --quick, the lessons shown are the quick ones (_add_quick), not ones named by id."""
    wanted = list(dict.fromkeys(args.targets))
    under = getattr(args, "under", None)
    if getattr(args, "quick", False):
        if wanted:
            print("okl on-edit add: --quick chooses the lessons by their checks' time; name lessons by id "
                  "or pass --quick, not both", file=sys.stderr)
            return 2
        return _add_quick(args, approved, nodes, client, QUICK if under is None else under)
    if under is not None:
        print("okl on-edit add: --under goes with --quick, which chooses the lessons by it", file=sys.stderr)
        return 2
    if not wanted:
        print("okl on-edit add: name the lessons by id (okl on-edit lists the ones that can be added), or "
              "pass --quick for the ones whose check is quick", file=sys.stderr)
        return 2
    bad = [(i, why) for i in wanted if (why := _why_not(nodes.get(i), client.repo))]
    if bad:
        for i, why in bad:
            print(f"okl on-edit: cannot add [{shown(i)}]: {why}", file=sys.stderr)
        return 2
    return _approve(args, wanted, approved, nodes)


def _add_quick(args: argparse.Namespace, approved: dict[str, str], nodes: dict[str, Node], client: Client,
               under: float) -> int | None:
    """Offer the lessons that could be added whose stored check last passed in at most `under`
    seconds, each shown with its time, and approve them as _approve does. The ones never timed are
    listed apart, by id and title, and never offered; the slow ones and the ones whose check last
    failed are counted."""
    if under > TIMEOUT:
        print(f"okl on-edit add: --under {under:g} is longer than the {TIMEOUT} seconds a check gets after an "
              "edit, so a check that slow would never be judged there", file=sys.stderr)
        return 2
    quick, unknown, slow, failing = _by_time(client, _addable(approved, nodes, client.repo), under)
    apart = []
    if unknown:
        apart.append("Time unknown, so --quick does not offer these: no run of their check has been timed yet.")
        apart.extend(f"  [{shown(n.id)}] {n.title}" for n in unknown)
        apart.append("`okl reverify --untimed` re-runs their checks once to time them; it shows them and asks "
                     "first.")
    left = [f"{slow} whose last passing run took over {under:g} s" if slow else "",
            f"{failing} whose check failed its last run" if failing else ""]
    if any(left):
        apart.append("Also left out: " + ", ".join(x for x in left if x) + ".")
    if not quick:
        print("\n".join([f"okl on-edit add --quick: no lesson's check last passed in {under:g} s or less, so "
                         "there is nothing to approve.", *apart]))
        return None
    times = {n.id: t for n, t in quick}
    return _approve(args, list(times), approved, nodes, times=times, apart=apart,
                    intro=(f"These {len(quick)} lesson checks" if len(quick) > 1 else "This lesson check")
                    + f" last passed in {under:g} s or less.")


def _approve(args: argparse.Namespace, wanted: list[str], approved: dict[str, str], nodes: dict[str, Node], *,
             times: dict[str, float] | None = None, apart: list[str] | None = None, intro: str = "") -> int | None:
    """Show each lesson's stored command (with its last time, given `times`), then `apart`, and approve
    them all on one yes, or --yes; refuse unattended without --yes. None when approved."""
    # A refusal leaves stdout empty, so where it will refuse, the plan goes to stderr with it.
    asking = args.yes or sys.stdin.isatty()
    out = sys.stdout if asking else sys.stderr
    if intro:
        print(intro, file=out)
    print("After EVERY edit the agent makes in this repository, okl will run each of these lessons' stored "
          "checks, a command from the store (first when the edit touches a file the lesson governs), so "
          "approve only checks that are quick:", file=out)
    for i in wanted:
        print(_offered(nodes[i], (times or {}).get(i)), file=out)
    for line in apart or []:
        print(line, file=out)
    if not asking:
        # Said to whoever ran it, often an agent: the way forward is a person, not a flag
        # (lesson refusal-offers-no-destructive-shortcut).
        print("refusing to approve stored commands unattended: a person reviews them above and "
              "approves them in a terminal", file=sys.stderr)
        return 2
    if not args.yes and input("Approve them? [y/N] ").strip().lower() not in ("y", "yes"):
        print("okl on-edit: not approved; nothing changed", file=sys.stderr)
        return 2
    for i in wanted:
        approved[i] = approval(*(_stored_check(nodes[i].verified_by) or ("", None)))
    return None


def _offered(node: Node, took: float | None = None) -> str:
    """One lesson as add shows it before asking: its files, the command it would run, the signal that
    command must print, and with `took`, how long its last passing run took."""
    run, expect = _stored_check(node.verified_by) or ("", None)
    return (f"  [{shown(node.id)}] {node.title}\n      files: {node.files or 'none'}\n      runs:  {run}"
            + (f"\n      passes when its output contains {expect!r}" if expect else "")
            + (f"\n      last passing run took {_took(took)}" if took is not None else ""))


def _remove(args: argparse.Namespace, approved: dict[str, str], _nodes: dict[str, Node],
            _client: Client) -> int | None:
    """Drop the named approvals in place; 2, changing nothing, when one was never approved."""
    unknown = [i for i in args.targets if i not in approved]
    if unknown:
        print(f"okl on-edit: not approved, so nothing to remove: {', '.join(map(shown, unknown))}", file=sys.stderr)
        return 2
    for i in args.targets:
        approved.pop(i, None)
    return None


def _addable(approved: dict[str, str], nodes: dict[str, Node], repo: str) -> list[Node]:
    """The lessons whose check could be approved and is not, by id."""
    return sorted((n for n in nodes.values() if n.id not in approved and _why_not(n, repo) is None),
                  key=lambda n: n.id)


FAILED = "failed"        # check_time: the latest run of the lesson's stored check failed
UNTIMED = "untimed"      # check_time: no timed passing run of it among the runs okl can see


def check_time(client: Client, node: Node) -> float | str:
    """How long the lesson's stored check (the command and signal an approval pins) took at its latest
    logged run, which passed; FAILED when that run failed; UNTIMED when it passed untimed (logged before
    okl timed runs) or the runs `okl show` lists hold none of it. A run of another command is another
    check, whatever it took. One test for both readers: `okl on-edit add --quick` lists the UNTIMED
    lessons apart, and `okl reverify --untimed` re-runs them once to time them."""
    check = _stored_check(node.verified_by)
    got = client.get(node.id) if check else None
    if not check or not got:
        return UNTIMED
    mine = [r for r in got.get("checks") or []
            if (r.get("command"), r.get("expect") or None) == (check[0], check[1] or None)]
    if not mine:
        return UNTIMED
    if not mine[-1].get("passed"):
        return FAILED
    took = mine[-1].get("seconds")
    timed = isinstance(took, int | float) and not isinstance(took, bool) and math.isfinite(took)
    return float(took) if timed else UNTIMED


def untimed(client: Client, nodes: dict[str, Node]) -> list[Node]:
    """The lessons whose check could run on edit, approved or not, and is UNTIMED, by id: the ones
    `okl on-edit add --quick` lists as time unknown, which `okl reverify --untimed` re-runs."""
    return [n for n in _addable({}, nodes, client.repo) if check_time(client, n) == UNTIMED]


def _by_time(client: Client, lessons: list[Node], under: float) -> tuple[list[tuple[Node, float]], list[Node], int, int]:
    """`lessons` sorted by their check's last run: the quick ones (last passed in at most `under`
    seconds) with that time, the UNTIMED ones, and how many were slow and how many last failed. A
    check whose latest run failed would fail at every edit, so it is not offered, however fast."""
    quick: list[tuple[Node, float]] = []
    unknown: list[Node] = []
    slow = failing = 0
    for n in lessons:
        took = check_time(client, n)
        if took == FAILED:
            failing += 1
        elif isinstance(took, str):     # UNTIMED
            unknown.append(n)
        elif took <= under:
            quick.append((n, took))
        else:
            slow += 1
    return quick, unknown, slow, failing


def _took(seconds: float) -> str:
    """A run's time as the lists show it."""
    return f"{seconds:.1f} s" if seconds >= 0.05 else "under 0.1 s"


def quick_hint(client: Client, approved: dict | None, nodes: dict[str, Node] | None = None) -> str | None:
    """The line `okl init` and `okl on-edit` say when no check is approved and some lessons' checks
    last passed in at most QUICK seconds; None when a check is approved or none is quick. None on a
    shared service too: it reads each lesson's runs, one request per lesson there, on every listing.
    Locally that is one indexed read per lesson, cheap at the size of okl's own store."""
    if approved or client.mode == "remote":
        return None
    if nodes is None:
        nodes = {n.id: n for n in client.all_nodes()}
    count = len(_by_time(client, _addable({}, nodes, client.repo), QUICK)[0])
    if not count:
        return None
    return (f"{count} lesson check{'' if count == 1 else 's'} ran in under {QUICK} s; "
            "`okl on-edit add --quick` shows them and asks.")


def _list(approved: dict[str, str], nodes: dict[str, Node], client: Client) -> None:
    """The approved checks, each with whether it still runs, then the lessons that could be added,
    and with none approved, how many of those are quick."""
    repo = client.repo
    if approved:
        print(f"{len(approved)} lesson check(s) run after every edit in this repository, those governing "
              "the edited file first:")
        for i, pinned in sorted(approved.items()):
            node = nodes.get(i)
            chk = _stored_check(node.verified_by) if node else None
            state = ("" if chk and approval(*chk) == pinned and _why_not(node, repo) is None
                     else "  (NOT RUN: " + (_why_not(node, repo) or "its stored check changed since it was "
                                             f"approved; review it with okl on-edit add {shown(i)}") + ")")
            print(f"  [{shown(i)}] {shown(node.title) if node else ''}{state}"
                  + (f"\n      runs: {shown(chk[0])}" if chk else ""))
    else:
        print("No lesson checks run on edit here. Approve the ones that are quick and need nothing but "
              "this checkout: okl on-edit add <id>...")
        hint = quick_hint(client, approved, nodes)
        if hint:
            print(hint)
    can = _addable(approved, nodes, repo)
    if can:
        print(f"{len(can)} more could be added (they carry a stored check):")
        for n in can:
            print(f"  [{shown(n.id)}] {n.title}\n      runs: {(_stored_check(n.verified_by) or ('',))[0]}")  # printable: _why_not


def _run(args: argparse.Namespace, root: Path, approved: dict[str, str], nodes: dict[str, Node], repo: str,
         *, started: float) -> int:
    """Run every approved check after an edit inside the repository, those of the lessons governing
    the edited files first (see the module's notes); report what failed.

    Exit 1 when a check failed; 2 when none failed but one could not be judged (out of time, its
    command changed since approval, its lesson gone), since a caller reads 0 as every check passing;
    0 when every check that ran passed, or the edit lies outside the repository. A check whose
    lesson does not govern the edited file starts only when its whole --timeout still fits in the
    budget; one that does not fit is skipped at this edit, said in the text output and not to the
    agent, since CI runs the same check and nothing the agent did made it slow. The path is read as
    the file briefing reads it, so a tracked symlink is governed by its own name (review of #441).
    """
    inside, _outside = _repo_relative(list(args.targets), root)
    rel = sorted(set(inside))
    governed = sorted((n for n in core.governing(list(nodes.values()), repo, set(rel)) if n.id in approved),
                      key=lambda n: n.id) if rel else []
    first = {n.id for n in governed}
    rest = sorted((n for i in approved if i not in first and (n := nodes.get(i)) is not None),
                  key=lambda n: n.id) if rel else []
    failed: list[tuple[Node, str, str | None, str, str, bool]] = []
    # An approval whose lesson is gone cannot run: said, so exit 0 still means every check that should run did.
    notes = [f"[{shown(i)}]: not run, because no lesson has this id any more; the person can drop it with "
             f"okl on-edit remove {shown(i)}" for i in sorted(approved) if rel and i not in nodes]
    skipped: list[str] = []
    passed = 0
    deadline = started + args.budget   # from okl's start, so a slow store read counts too
    for n in governed + rest:   # in this order: the budget is spent on the governing lessons first
        mine = n.id in first
        chk = _stored_check(n.verified_by)
        why = _why_not(n, repo)
        if chk is None or why or approval(*chk) != approved[n.id]:
            notes.append(f"[{shown(n.id)}] {shown(n.title)}: not run, because "
                         + (why or ("its stored check changed since it was approved" if chk else
                                    "its stored check is gone"))
                         + f"; the person can review it with okl on-edit add {shown(n.id)}")
            continue
        left = deadline - time.monotonic()
        if not mine and left < args.timeout:
            skipped.append(shown(n.id))
            continue
        if left <= 0:
            notes.append(f"[{shown(n.id)}] {n.title}: not run, out of time for this edit ({args.budget}s)")
            continue
        run, expect = chk
        timeout = max(1, min(args.timeout, math.ceil(left)))
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            result = _run_check(argparse.Namespace(run=run, expect=expect, timeout=timeout, cwd=root))
        if result.output is not None:
            passed += 1
        elif result.timed_out:
            notes.append(f"[{shown(n.id)}] {n.title}: its check did not finish in {timeout}s, so it was not judged")
        else:
            failed.append((n, run, expect, result.outcome, said.getvalue(), mine))
    text = _report(rel, failed, notes)
    code = 1 if failed else 2 if notes else 0
    later = (f"okl on-edit: not run at this edit, too little of the {args.budget}s budget left for their "
             f"--timeout: {', '.join(skipped)}; they run at an edit with time to spare, and in CI") if skipped else ""
    if args.format == "hook":
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    elif code == 2:
        print("\n".join(x for x in (text, later) if x), file=sys.stderr)
    else:
        ran = governed or rest
        print("\n".join(x for x in (
            text or (f"okl on-edit: {passed} approved check(s) passed for {', '.join(rel)}" if ran
                     else f"okl on-edit: no approved check ran for {', '.join(rel) or 'these files'}"
                     + ("" if rel else " (outside this repository)")), later) if x))
    return code


def _report(paths: list[str], failed: list, notes: list[str]) -> str:
    """What the agent is told: each failing lesson with its fix, the command and the end of its
    output, then anything not run. Empty when every check passed. A failing check of a lesson that
    governs the edited file is the agent's to fix; one whose lesson does not govern it may have
    failed before this edit, so the agent is told to find out first, not to fix code it never
    touched on the strength of it."""
    lines: list[str] = []
    here = [f for f in failed if f[5]]
    elsewhere = [f for f in failed if not f[5]]
    if here:
        lines.append(f"OKL CHECK FAILED after editing {', '.join(paths)}: a lesson that governs this file "
                     "carries a check, and the check fails now.")
        lines.extend(_failure_lines(here))
        lines.append("Fix the code so the check passes, and run it again yourself to see. If the lesson itself "
                     "is out of date, say so to the person rather than changing the check. okl recorded nothing.")
    if elsewhere:
        lines.append(f"OKL CHECK FAILED{' also' if here else ''} after editing {', '.join(paths)}: a check you "
                     "approved for the whole repository fails now. Its lesson does not govern this file, so it "
                     "may have failed before this edit.")
        lines.extend(_failure_lines(elsewhere))
        lines.append("Find out first whether your change caused it (run the check on the code without your "
                     "change, or read what it tests). If it did, fix that; if it failed already, say so to the "
                     "person and leave that code alone. okl recorded nothing.")
    if notes:
        lines.append("OKL: some checks for this edit were not run:" if not failed else "Also not run:")
        lines.extend(f"- {s}" for s in notes)
    return "\n".join(lines)


def _failure_lines(failed: list) -> list[str]:
    """Each failing lesson: its title, its fix, the command and the end of what it printed."""
    lines: list[str] = []
    for n, run, expect, outcome, said, _mine in failed:
        fix = " ".join((n.fix or "").split())
        lines.append(f"- [{shown(n.id)}] {n.title}")
        if fix:
            lines.append(f"  fix: {shown(fix[:400])}")
        lines.append(f"  check: {run}" + (f"  (passes when its output contains {expect!r})" if expect else ""))
        tail = [ln for ln in said.splitlines()[1:] if ln.strip()]
        lines.append(f"  result: {outcome}" + (": the last lines it printed:" if tail else ""))
        lines.extend(f"    {ln}" for ln in tail)
    return lines
