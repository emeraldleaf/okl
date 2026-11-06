"""Reports on the install and the store: `okl doctor`, `okl metric`, `okl coverage`."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from ..client import Client, OKLUnreachableError, _find_config
from .common import _print_json


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report agent-memory tools installed beside okl and how they collide (#40).

    Exit 1 when any is found, or when okl itself is wired twice (its plugin enabled AND
    its hooks registered in the project or user settings, so every prompt is briefed
    twice) -- findings,
    per the CLI contract -- and 0 when neither is. It reads settings files, asks git where
    its hooks live, and, where `okl init --owner` set an owner, asks GitHub through gh whether
    the owner's approval is enforced (a few reads; informational, not a finding). Where a
    store exists it reads its lessons, to say which the interests keep out of briefings
    (#374): informational too. It writes nothing, beyond the schema upgrade any command
    makes when it opens an older store.
    """
    from .. import coexist
    cfg = _find_config()
    root = cfg.parent.parent if cfg else Path.cwd()
    found = coexist.detect(root, Path.home())
    print(coexist.render(found))
    twice = coexist.double_wiring(root, Path.home())
    if twice:
        print(f"\n! {twice}")
    # Informational: a choice, not a finding (#111). A diagnostic must not end in a
    # traceback, so an unreadable config simply does not report it (CodeRabbit on #112).
    try:
        ci_off = cfg is not None and json.loads(cfg.read_text()).get("ci") is False
    except (OSError, ValueError, AttributeError):
        ci_off = False
    if ci_off:
        print("\n• drift is not gated in CI here; `okl init --ci` adds the GitHub workflow, and "
              "another CI can run `okl drift --gate`")
    print(_git_hook_state(root))
    try:
        recorded = json.loads(cfg.read_text()) if cfg else {}
    except (OSError, ValueError):
        recorded = {}
    owners = _owner_state(root, recorded if isinstance(recorded, dict) else {})
    if owners:
        print(owners)
    for line in _interest_lines(Client()):
        print(line)
    return 1 if (found or twice) else 0


def _interest_lines(client: Client, *, say_unread: bool = True, shown: int = 5) -> list[str]:
    """What this repo's interests keep out of its briefings (#374), for doctor and init.

    Informational, as the interest list is a choice a re-run of init keeps (#340). That is
    also why a later default never reached a repo set up before it, and nothing said so.
    Silent with no store to read, since reading one would create it. A store that cannot
    be read, refused or unreachable, gets one line saying so with `say_unread`, so silence
    never stands for "nothing hidden"; never an error, since the command already did its job.
    """
    import sqlite3

    from .. import core
    from ..client import OKLRejectedError
    from ..store import split_tags
    if not client.configured or not client.interests or _no_store_yet(client):
        return []
    try:
        hidden = core.hidden_by_interests(client.all_nodes(), client.repo, client.interests)
    except (OKLUnreachableError, OKLRejectedError, OSError, sqlite3.Error) as e:   # a corrupt file too
        why = (str(e).strip().splitlines() or [type(e).__name__])[0]
        return [f"\n• what this repo's interests hide: not reported, the store could not be read ({why})"] \
            if say_unread else []
    if not hidden:
        return []
    have = {t.strip().lower() for t in client.interests}
    missing = sorted(core.DEFAULT_INTERESTS - have)
    lines = [f"\n• this repo's interests ({', '.join(client.interests)}) keep {len(hidden)} org "
             "lesson(s) out of every briefing"]
    if missing:
        revealed = sum(1 for n in hidden if split_tags(n.tags) & set(missing))
        lines.append(f"  okl's default subject(s) {', '.join(missing)} are not among them, and would "
                     f"show {revealed} of these: okl init --interests {','.join(sorted(have | set(missing)))}")
    subjects = Counter(t for n in hidden for t in split_tags(n.tags))
    lines.append("  their subjects: " + ", ".join(f"{t} ({c})" for t, c in subjects.most_common(6)))
    if not missing:
        lines.append(f"  to brief one, add its subject: okl init --interests {','.join(sorted(have))},<subject>")
    # The ones a missing default would bring back first: they are what the offer is about.
    first = sorted(hidden, key=lambda n: (not split_tags(n.tags) & set(missing), n.id))
    lines += [f"  [{n.id}] {n.title}" for n in first[:shown]]
    if len(hidden) > shown:
        lines.append(f"  … and {len(hidden) - shown} more")
    return lines


def _no_store_yet(client: Client) -> bool:
    """Whether this repo's local SQLite store does not exist, so a read would create it."""
    if client.mode == "remote":
        return False
    url = os.environ.get("OKL_DATABASE_URL")
    if not url:   # empty is unset, as Client._local_store reads it
        cfg = _find_config()
        return cfg is None or not (cfg.parent / "okl.db").exists()
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        return not Path(url.removeprefix("sqlite:///")).exists()
    return False


def _owner_state(root: Path, cfg: dict) -> str:
    """okl's owner-approved paths (#329): whether GitHub enforces the owner's approval, then each
    path's owner on the default branch. The owner and paths come from what `okl init --owner`
    recorded; a clone without them (.okl/ is not committed) checks the owner okl's block names on
    the default branch, where a committed CODEOWNERS holds the block. Empty, and no API call made,
    where neither does: whether it runs is decided from committed files, not the working tree."""
    from .. import codeowners, protection
    owner = cfg.get("owner")
    if not owner and not _committed_block(root):
        return ""
    verdict = (protection.check(codeowners.owner_paths(cfg.get("owned", [])), owner) if owner
               else protection.check(None, None))
    mark = {protection.ENFORCED: "✓", protection.NOT_ENFORCED: "!"}.get(verdict.state, "•")
    who = owner or verdict.owner
    lines = [f"\n{mark} owner-approved paths{f' for {who}' if who else ''}: {verdict.state}. {verdict.why}"]
    for p, found in verdict.owners.items():
        held = ("okl could not tell" if found is None else f"owned by {' '.join(found)}" if found else "no owner")
        lines.append(f"    {p}: {held}")
    return "\n".join(lines)


def _committed_block(root: Path) -> bool:
    """Whether a CODEOWNERS committed at HEAD, or on the default branch (origin/HEAD), holds okl's
    block: read from git as bytes, never the working tree, and never a traceback (no git, a
    CODEOWNERS that is not UTF-8)."""
    import subprocess

    from .. import codeowners
    marker = codeowners.BEGIN.encode()
    for ref in ("HEAD", "refs/remotes/origin/HEAD"):
        for location in codeowners.LOCATIONS:
            try:
                r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{location.as_posix()}"],
                                   capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                return False
            if r.returncode == 0 and marker in r.stdout:
                return True
    return False


def _git_hook_state(root: Path) -> str:
    """One informational line on the pre-push drift gate (#90): okl's, edited, or absent."""
    from .. import ownership
    from .install import GIT_HOOK_SRC, _git_hooks_dir
    hooks, why = _git_hooks_dir(root)
    if hooks is None:
        return f"\n• pre-push drift gate: cannot be installed here ({why})"
    rel = hooks / "pre-push"
    state = ownership.status(root / rel, GIT_HOOK_SRC.read_text())
    if state == ownership.OKL:
        return f"\n• pre-push drift gate: installed ({rel})"
    if state == ownership.MODIFIED:
        return f"\n• pre-push drift gate: installed and edited since okl wrote it ({rel})"
    other = " (another tool's pre-push hook is there)" if state == ownership.UNKNOWN else ""
    return f"\n• pre-push drift gate: not installed{other}; `okl init --git-hook` installs it"


def cmd_metric(args: argparse.Namespace) -> int:
    """Recurrence, with the coverage that makes the number readable (issue #31)."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — refusing to report a metric about a store that is not "
              "there. Run `okl init` or `okl connect <url>`.", file=sys.stderr)
        return 2
    try:
        report = client.recurrence_report()
        exposure = client.exposure_report() if report is not None else None
        hygiene = client.hygiene_report() if report is not None else None
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot compute metric.\n{e}", file=sys.stderr)
        return 2
    if report is None:
        print("OKL: the connected service predates the coverage report, so this metric's "
              "coverage is unknown. Upgrade the service before reading it.", file=sys.stderr)
        return 2
    if args.format == "json":
        _print_json({**report, "exposure": exposure, "hygiene": hygiene})
        return 0
    armed, unarmed = report["armed"], report["unarmed"]
    total, gated = report["defects"], report["defects_with_gate"]
    pct = f" ({100 * gated // total}%)" if total else ""
    # No tick. "0" here speaks only for defects that have a gate; the line says how many
    # that is, so a low-coverage zero cannot read as a result.
    print(f"recurrence-after-arming: {len(armed)} — among the {gated} of {total} "
          f"defects that have a gate{pct}")
    for r in armed:
        print(f"  {r['defect_class']}  recurred in {r['recurred_in']}  "
              f"(gate: {', '.join(r['gates'])})")
    print(f"recurrence without a gate: {len(unarmed)}"
          + (" — lessons that were written down and came back anyway:" if unarmed else ""))
    for r in unarmed:
        print(f"  {r['defect_class']}  recurred in {r['recurred_in']}")
    _print_exposure(exposure)
    _print_hygiene(hygiene)
    return 0


def _print_hygiene(report: dict | None) -> None:
    """The hygiene lines of `okl metric` (#252): stale-use and over-scope, denominators first."""
    if report is None:
        print("\nhygiene: unknown — the connected service predates the hygiene report")
        return
    su, os_ = report["stale_use"], report["over_scope"]
    if not su["briefings"]:
        print("\nstale-use: no briefings logged yet, so not reported")
    else:
        print(f"\nstale-use: {su['with_drifted']} of {su['briefings']} logged briefings included "
              "a lesson whose code had changed since its last check")
        for r in su["lessons"]:
            print(f"  [{r['id']}] {r['title']} — stale in {r['times']} briefing(s)")
    print(f"over-scope: {os_['flagged']} of {os_['org_lessons']} org lessons name one "
          "repository's world in their title, symptom or fix")
    for r in os_["lessons"]:
        print(f"  [{r['id']}] {r['title']} — {'; '.join(r['signals'])}")
    ts = report["trace_shaped"]
    if ts["flagged"]:
        print(f"trace-shaped: {ts['flagged']} of {ts['org_lessons']} org lessons read as a pasted "
              "transcript rather than a lesson")
        for r in ts["lessons"]:
            print(f"  [{r['id']}] {r['title']} — {'; '.join(r['signals'])}")


def _print_hidden(report: dict) -> None:
    # Outside every figure above, so said beside them (#374). A service older than the count
    # sends no key, and then nothing is claimed either way.
    if report.get("hidden_by_interests"):
        print(f"kept out by this repo's interests, so in none of the exposure figures: "
              f"{report['hidden_by_interests']} org lesson(s); `okl doctor` names them")


def _print_exposure(report: dict | None) -> None:
    """The briefing-exposure lines of `okl metric` (#129), led by what they cover."""
    if report is None:
        print("\nbriefing exposure: unknown — the connected service predates the briefing log")
        return
    n = report["briefings"]
    if not n:
        # Zero briefings logged says nothing about any lesson. Report the absence, not a
        # list of every lesson as "never shown".
        print("\nbriefings logged: none yet, so which lessons get shown is not reported. "
              "The log fills as okl check runs (OKL_BRIEFING_LOG=0 turns it off).")
        _print_hidden(report)
        return
    since = datetime.fromtimestamp(report["first_at"] / 1000, tz=UTC).date()
    print(f"\nbriefings logged: {n} since {since} — the figures below cover only these")
    print(f"lessons this repo can be briefed: {report['reachable']} — shown at least once: "
          f"{report['shown']}, never shown: {report['never_shown_count']}")
    _print_hidden(report)
    if report["never_shown"]:
        print("  never shown, oldest first (review or retire?):")
        for r in report["never_shown"]:
            print(f"    [{r['id']}] {r['title']}")
        more = report["never_shown_count"] - len(report["never_shown"])
        if more > 0:
            print(f"    … and {more} more")
    if report["most_shown_unchecked"]:
        print("  shown most often with no stored check (worth an `okl verify --run`?):")
        for r in report["most_shown_unchecked"]:
            print(f"    [{r['id']}] {r['title']} — in {r['times']} of {n} briefings")


def cmd_coverage(args: argparse.Namespace) -> int:
    """Knowledge-to-code ratio — a health signal, not a target (Codified Context §4.2)."""
    import subprocess
    client = Client()
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot compute coverage.\n{e}", file=sys.stderr)
        return 2
    repo = args.repo or client.repo
    in_scope = [n for n in nodes if n.scope == "org" or n.scope == f"repo:{repo}"]
    knowledge_lines = sum(len((n.body or "").splitlines()) + 1 for n in in_scope)
    # code lines: git ls-files line count, or None if not a repo
    code_lines = None
    try:
        files = subprocess.run(["git", "-C", args.repo_dir, "ls-files"],
                               capture_output=True, text=True, timeout=15)
        if files.returncode == 0:
            code_lines = 0
            for f in files.stdout.splitlines():
                fp = Path(args.repo_dir) / f
                if fp.suffix.lower() in {".py",".cs",".ts",".tsx",".js",".jsx",".go",".rs",".java",".rb"}:
                    with contextlib.suppress(OSError):
                        code_lines += sum(1 for _ in fp.open("rb"))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    ratio = (knowledge_lines / code_lines) if code_lines else None
    out = {"nodes_in_scope": len(in_scope), "knowledge_lines": knowledge_lines,
           "code_lines": code_lines,
           "knowledge_to_code": round(ratio, 4) if ratio is not None else None}
    if args.format == "json":
        _print_json(out); return 0
    print(f"OKL coverage for {repo}:")
    print(f"  encoded nodes in scope : {out['nodes_in_scope']}")
    print(f"  knowledge lines        : {out['knowledge_lines']}")
    print(f"  code lines             : {out['code_lines'] if out['code_lines'] is not None else '(not a git repo)'}")
    if ratio is not None:
        print(f"  knowledge-to-code      : {ratio:.1%}  (health signal — a sudden spike in agent confusion "
              "means a relevant node is missing or stale, not that this number is wrong)")
    return 0
