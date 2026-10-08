"""The argparse table for every `okl` command: the CLI's whole contract in one place."""
from __future__ import annotations

import argparse

from .. import __version__, core
from .health import cmd_coverage, cmd_doctor, cmd_metric
from .install import cmd_connect, cmd_init, cmd_scaffold
from .lessons import cmd_bootstrap, cmd_check, cmd_dedup, cmd_link, cmd_record, cmd_search
from .packs import cmd_seed
from .servers import cmd_mcp, cmd_serve
from .verification import cmd_drift, cmd_export, cmd_reverify, cmd_verify


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 - one declarative table, see below
    """Build the argparse tree for every subcommand.

    One long declarative function on purpose: the parser IS the CLI's contract, and a
    reader answering "what flags does verify take" should find the whole answer in one
    place rather than following a chain of registration helpers.
    """
    p = argparse.ArgumentParser(prog="okl", description="Observed Knowledge Ledger — lessons your coding agents can trust, proven by checks.")
    # The installed distribution's version, read from package metadata (okl.__version__),
    # so a repo pinned to a release can tell which one its hooks are running.
    p.add_argument("--version", action="version", version=f"okl {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="wire the current repo (config + hook + CI pointer)")
    pi.add_argument("--repo"); pi.add_argument("--service")
    pi.add_argument("--interests", help="comma-sep subject tags this repo cares about "
                    "(filters org-scope lessons in `check`; see store.KNOWN_TAGS)")
    pi.add_argument("--claude", action=argparse.BooleanOptionalAction, default=None,
                    help="--claude wires Claude Code (hooks, settings, MCP) even with no .claude/ "
                         "and no `claude` on PATH; --no-claude skips it. Default: wire when "
                         ".claude/ exists or `claude` is on PATH")
    pi.add_argument("--ci", action=argparse.BooleanOptionalAction, default=None,
                    help="--no-ci skips the GitHub Actions drift workflow (a private repo pays for its "
                         "minutes; another CI or a hook can run `okl drift --gate`) and records that in "
                         ".okl/config.json so later runs skip it too; --ci turns it back on")
    pi.add_argument("--git-hook", dest="git_hook", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="--git-hook installs a git pre-push hook that runs `okl drift --gate` and "
                         "blocks a push only when lessons have drifted (core.hooksPath honoured; "
                         "another tool's pre-push hook is never replaced). Recorded in "
                         ".okl/config.json so later runs upgrade it; --no-git-hook stops that")
    pi.add_argument("--no-seed", dest="no_seed", action="store_true",
                    help="leave the store empty (by default init imports the starter lessons and "
                         "the bundled packs that match this repo's stack)")
    pi.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="list every file init would write or modify, and write nothing")
    pi.add_argument("--force", action="store_true",
                    help="replace okl files you have edited with okl's version")
    pi.add_argument("--uninstall", action="store_true",
                    help="remove okl's hooks, registrations and CI workflow (never .okl/); "
                         "edited files are kept. Combine with --dry-run to preview")
    pi.set_defaults(func=cmd_init)

    pc = sub.add_parser("connect", help="point this repo at a shared OKL service URL")
    pc.add_argument("url"); pc.add_argument("--token")
    pc.set_defaults(func=cmd_connect)

    pk = sub.add_parser("check", help="pre-task read: relevant lessons for a task")
    pk.add_argument("--task", required=True); pk.add_argument("--repo")
    pk.add_argument("--format", choices=["agent", "actions", "json", "hook"], default="agent",
                    help="agent: the full briefing. actions: the routed action list only, "
                         "for callers on a small context budget. json: the raw result. hook: what a "
                         "Claude Code UserPromptSubmit hook prints (briefing + a line for the user).")
    pk.add_argument("--limit", type=int, default=None,
                    help="cap how many records the briefing draws on (and how many actions "
                         "'--format actions' prints). Use with subagents on a token budget.")
    pk.add_argument("--compact", action="store_true",
                    help="only the action list, in the agent and hook formats: roughly half the "
                         "tokens at the same --limit. For models with a small context window; "
                         "the prompt hook sets it from OKL_BRIEFING_COMPACT=1.")
    pk.add_argument("--interests", default=None,
                    help="override this repo's configured subject tags for this call. Pass "
                         "an empty string to disable interest filtering entirely — the eval "
                         "harness does, because inheriting a host repo's interests made one "
                         "of its tasks measure the absence of the rule it tests.")
    pk.set_defaults(func=cmd_check)

    pr = sub.add_parser("record", help="record a node (defect/gate/claim/...)")
    pr.add_argument("--type", required=True); pr.add_argument("--title", required=True)
    pr.add_argument("--scope", required=True, help="'org' or 'repo:<name>' or 'repo'")
    pr.add_argument("--repo"); pr.add_argument("--body"); pr.add_argument("--status")
    pr.add_argument("--found-by", dest="found_by")
    pr.add_argument("--ttl-days", dest="ttl_days", type=int); pr.add_argument("--owner")
    pr.add_argument("--files", help="comma-sep path globs this node governs (enrolls it in drift detection)")
    pr.add_argument("--symptom", help="Symptom→Cause→Fix: the observable symptom (cause goes in --body)")
    pr.add_argument("--fix", help="Symptom→Cause→Fix: the fix to apply")
    pr.add_argument("--applies-to", dest="applies_to", default=None,
                    help="stacks this lesson is VALID for (comma-sep), or 'any'. Leave unset "
                         "for a portable lesson — that is the default and the common case. "
                         "Use it only when the lesson genuinely does not transfer, e.g. a "
                         "framework's middleware ordering. Distinct from --tags, which "
                         "records subject and where the lesson was found.")
    pr.add_argument("--tags", help="comma-sep subject tags from the controlled vocabulary "
                    "(store.KNOWN_TAGS), e.g. 'react,security'")
    pr.add_argument("--id", help="explicit stable id (makes the write idempotent — re-records replace)")
    pr.add_argument("--verified", action="store_true",
                    help="refused: verify with `okl verify <id> --run ... --expect ...` instead")
    pr.set_defaults(func=cmd_record)

    pl = sub.add_parser("link", help="add an edge between two nodes")
    pl.add_argument("src"); pl.add_argument("rel"); pl.add_argument("dst")
    pl.set_defaults(func=cmd_link)

    pvf = sub.add_parser("verify", help="run a check and stamp a node verified only on an observed pass")
    pvf.add_argument("node_id")
    pvf.add_argument("--run", help="the check command; exit 0 required to stamp. Without it, "
                     "okl verify shows the lesson and the tests that touch its files, and stamps nothing")
    pvf.add_argument("--expect", help="substring that must appear in the output — a positive success "
                     "signal, so exit 0 alone can't self-certify (the exit-0-zero-files lesson)")
    pvf.add_argument("--timeout", type=int, default=600, help="seconds before the check is killed (default 600)")
    pvf.set_defaults(func=cmd_verify)

    prv = sub.add_parser("reverify", help="re-run the stored check of every drifted lesson, and of any last checked on another branch, and re-stamp the passes")
    prv.add_argument("--yes", action="store_true",
                     help="run the listed stored commands without asking (they come from the store)")
    prv.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="list what would be re-run, run nothing")
    prv.add_argument("--timeout", type=int, default=600)
    prv.set_defaults(func=cmd_reverify)

    ps = sub.add_parser("search", help="full-text search over the encoded body")
    ps.add_argument("query")
    ps.add_argument("--scope", help="'org', 'repo:<name>', or 'repo' for this repo "
                                    "(anything else is refused, not silently empty)")
    ps.add_argument("--type", nargs="*"); ps.add_argument("--limit", type=int, default=25)
    ps.add_argument("--format", choices=["text", "json"], default="text")
    ps.set_defaults(func=cmd_search)

    pm = sub.add_parser("metric", help="recurrence-after-arming metric")
    pm.add_argument("--format", choices=["text", "json"], default="text")
    pm.set_defaults(func=cmd_metric)

    pdr = sub.add_parser("drift", help="source-vs-spec drift: rules whose governed code changed after verification")
    pdr.add_argument("--repo"); pdr.add_argument("--repo-dir", dest="repo_dir", default=".")
    pdr.add_argument("--gate", action="store_true", help="exit 1 if drift found (for CI)")
    pdr.add_argument("--format", choices=["text", "json"], default="text")
    pdr.add_argument("--snapshot", metavar="FILE",
                     help="read rules from a committed snapshot (okl export --drift) "
                          "instead of a store — for CI with no store")
    pdr.set_defaults(func=cmd_drift)

    pex = sub.add_parser("export", help="write the committed drift snapshot CI reads (okl-drift.json)")
    pex.add_argument("--drift", action="store_true", required=True,
                     help="the drift snapshot (the only export today; named so others can follow)")
    pex.add_argument("-o", "--output", help="path (default: okl-drift.json at the project root)")
    pex.set_defaults(func=cmd_export)

    pdoc = sub.add_parser("doctor", help="report other agent-memory tools installed beside okl, "
                                         "and how they collide (changes nothing)")
    pdoc.set_defaults(func=cmd_doctor)

    pdd = sub.add_parser("dedup", help="report near-duplicate records for review (never auto-merges)")
    pdd.add_argument("--threshold", type=float, default=core.DEDUP_THRESHOLD,
                     help=f"similarity 0-1 to report at (default {core.DEDUP_THRESHOLD}, "
                          "calibrated to over-report)")
    pdd.add_argument("--limit", type=int, default=20, help="pairs to print")
    pdd.set_defaults(func=cmd_dedup)
    pcv = sub.add_parser("coverage", help="knowledge-to-code ratio (health signal)")
    pcv.add_argument("--repo"); pcv.add_argument("--repo-dir", dest="repo_dir", default=".")
    pcv.add_argument("--format", choices=["text", "json"], default="text")
    pcv.set_defaults(func=cmd_coverage)

    pb = sub.add_parser("bootstrap", help="propose starter nodes from repo signals (git log, docs)")
    pb.add_argument("--repo"); pb.add_argument("--repo-dir", dest="repo_dir", default=".")
    pb.add_argument("--out", default="okl-bootstrap.json")
    pb.set_defaults(func=cmd_bootstrap)

    pd = sub.add_parser("seed", help="ingest seed file(s) as nodes (a *-defects.json, or a dir of them)")
    pd.add_argument("path", nargs="?", default=None,
                    help="a seed JSON file, or a directory of them. With no path, lists the "
                         "bundled packs and imports nothing.")
    pd.add_argument("--all", action="store_true",
                    help="import every bundled pack. Explicit on purpose: the packs carry "
                         "stack-specific rules, and importing all of them into an unrelated "
                         "project fills its briefings with noise.")
    pd.set_defaults(func=cmd_seed)

    psc = sub.add_parser("scaffold", help="stamp the portable method kit into a repo")
    psc.add_argument("target", nargs="?", default=".", help="target repo dir (default: cwd)")
    psc.add_argument("--repo", help="repo name (default: dir name)")
    psc.add_argument("--plugin", action="store_true", help="also write .claude-plugin/plugin.json (Claude Code plugin)")
    from ..scaffold_cmd import list_profiles
    psc.add_argument("--profile", action="append", choices=list_profiles(), metavar="PROFILE",
                     help="drop a stack's verbatim canon into .claude/rules/; repeatable and composable, "
                          f"e.g. --profile dotnet --profile react (available: {', '.join(list_profiles())})")
    psc.add_argument("--force", action="store_true", help="overwrite existing files")
    psc.add_argument("--verbose", "-v", action="store_true")
    psc.set_defaults(func=cmd_scaffold)

    pv = sub.add_parser("serve", help="run the shared FastAPI service")
    pv.add_argument("--host", default="0.0.0.0"); pv.add_argument("--port", type=int, default=8080)
    pv.set_defaults(func=cmd_serve)

    pmcp = sub.add_parser("mcp", help="run the MCP server (stdio) for agent tools")
    pmcp.set_defaults(func=cmd_mcp)
    return p
