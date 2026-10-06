"""Reports on the install and the store: `okl doctor`, `okl metric`, `okl coverage`."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..client import Client, OKLUnreachableError, _find_config
from .common import _print_json


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report agent-memory tools installed beside okl and how they collide (#40).

    Exit 1 when any is found, or when okl itself is wired twice (its plugin enabled AND
    its hooks registered in the project or user settings, so every prompt is briefed
    twice) -- findings,
    per the CLI contract -- and 0 when neither is. It reads settings files only and
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
        print("\n• drift is not gated in CI here (okl init --no-ci); run `okl drift --gate` from "
              "another CI or a git hook")
    return 1 if (found or twice) else 0


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
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot compute metric.\n{e}", file=sys.stderr)
        return 2
    if report is None:
        print("OKL: the connected service predates the coverage report, so this metric's "
              "coverage is unknown. Upgrade the service before reading it.", file=sys.stderr)
        return 2
    if args.format == "json":
        _print_json({**report, "exposure": exposure})
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
    return 0


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
    since = datetime.fromtimestamp(report["first_at"] / 1000, tz=timezone.utc).date()
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
