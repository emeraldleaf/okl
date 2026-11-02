"""Reports on the install and the store: `okl doctor`, `okl metric`, `okl coverage`."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
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
    the owner's approval is enforced (up to seven reads; informational, not a finding). It
    changes nothing.
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
    return 1 if (found or twice) else 0


def _owner_state(root: Path, cfg: dict) -> str:
    """okl's owner-approved paths (#329): whether GitHub enforces the owner's approval, then each
    path's owner on the default branch. The paths come from what `okl init --owner` recorded (or,
    failing that, okl's block in CODEOWNERS), since GitHub reads the merged file, not this working
    tree's. Empty, and no API call made, where no owner was set."""
    from .. import codeowners, protection
    owner, paths = cfg.get("owner"), codeowners.owner_paths(cfg.get("owned", []))
    if not owner:
        path = root / codeowners.location(root)
        try:
            block = codeowners.owned(path.read_bytes().decode("utf-8")) if path.is_file() else {}
        except (OSError, UnicodeDecodeError, codeowners.MalformedBlockError) as e:
            return f"\n! owner-approved paths: not enforced. {path.name} cannot be read as okl wrote it ({e})"
        if not block:
            return ""
        names = sorted({o for found in block.values() for o in found})
        if not names:
            # A hand edit left okl's block with paths and no owner: say so, never a traceback.
            return (f"\n! owner-approved paths ({', '.join(block)}): not enforced. okl's block in {path.name} "
                    "names no owner; `okl init --owner @you` writes it again")
        owner, paths = names[0], list(block)
    verdict = protection.check(paths, owner)
    mark = {protection.ENFORCED: "✓", protection.NOT_ENFORCED: "!"}.get(verdict.state, "•")
    lines = [f"\n{mark} owner-approved paths for {owner}: {verdict.state}. {verdict.why}"]
    for p, found in verdict.owners.items():
        held = ("a glob in CODEOWNERS may own it" if found is None
                else f"owned by {' '.join(found)}" if found else "no owner")
        lines.append(f"    {p}: {held}")
    return "\n".join(lines)


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
        return
    since = datetime.fromtimestamp(report["first_at"] / 1000, tz=UTC).date()
    print(f"\nbriefings logged: {n} since {since} — the figures below cover only these")
    print(f"lessons this repo can be briefed: {report['reachable']} — shown at least once: "
          f"{report['shown']}, never shown: {report['never_shown_count']}")
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
