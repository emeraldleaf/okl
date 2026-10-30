"""The argparse table for every `okl` command: the CLI's whole contract in one place."""
from __future__ import annotations

import argparse

from .. import __version__, core, semantic
from .embed import cmd_embed
from .health import cmd_coverage, cmd_doctor, cmd_metric
from .install import cmd_connect, cmd_init, cmd_scaffold
from .lessons import (
    cmd_bootstrap,
    cmd_check,
    cmd_dedup,
    cmd_link,
    cmd_recap,
    cmd_record,
    cmd_retire,
    cmd_search,
    cmd_show,
    cmd_triggers,
    cmd_update,
)
from .packs import cmd_seed
from .servers import cmd_mcp, cmd_serve
from .verification import cmd_drift, cmd_export, cmd_reverify, cmd_verify
from .warm import cmd_warm


def _days_or_blank(value: str) -> int | str:
    """`okl update --ttl-days`: a whole number of days, or "" to clear it, as an empty
    value clears every other optional field."""
    return "" if not value.strip() else int(value)


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 - one declarative table, see below
    """Build the argparse tree for every subcommand.

    One long declarative function on purpose: the parser IS the CLI's contract, and a
    reader answering "what flags does verify take" should find the whole answer in one
    place rather than following a chain of registration helpers.
    """
    p = argparse.ArgumentParser(prog="okl", description="Observed Knowledge Ledger — verified memory for coding agents, proven by checks.")
    # The installed distribution's version, read from package metadata (okl.__version__),
    # so a repo pinned to a release can tell which one its hooks are running.
    p.add_argument("--version", action="version", version=f"okl {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="wire the current repo (config, Claude Code hooks, MCP, pre-push drift gate; --ci for the GitHub workflow)")
    pi.add_argument("--repo"); pi.add_argument("--service")
    pi.add_argument("--interests", help="comma-sep subject tags this repo cares about "
                    "(filters org-scope lessons in `check`; see store.KNOWN_TAGS)")
    pi.add_argument("--claude", action=argparse.BooleanOptionalAction, default=None,
                    help="--claude wires Claude Code (hooks, settings, MCP) even with no .claude/ "
                         "and no `claude` on PATH; --no-claude skips it. Default: wire when "
                         ".claude/ exists or `claude` is on PATH")
    pi.add_argument("--ci", action=argparse.BooleanOptionalAction, default=None,
                    help="--ci installs the GitHub Actions drift workflow (opt-in: a private repo pays "
                         "for its minutes, and another CI can run `okl drift --gate`); --no-ci skips "
                         "it. Default: keep it where okl installed it before. Recorded in "
                         ".okl/config.json so later runs keep the choice")
    pi.add_argument("--git-hook", dest="git_hook", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="--git-hook installs a git pre-push hook that runs `okl drift --gate` and "
                         "blocks a push only when lessons have drifted (core.hooksPath honoured; "
                         "another tool's pre-push hook is never replaced); --no-git-hook skips it. "
                         "Default: installed wherever okl's GitHub workflow is not. Recorded in "
                         ".okl/config.json so later runs upgrade it")
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
    pk.add_argument("--hybrid", nargs="?", const="linear", choices=["rrf", "linear", "off"], default=None,
                    help="fuse the full-text candidates with the nearest records by a local embedding "
                         "(linear, the measured configuration and the default when the flag is bare, "
                         "or rrf); 'off' for full-text "
                         "only. Omit it to follow the config's `hybrid` or OKL_HYBRID. Needs `okl "
                         "embed` to have run once; otherwise the briefing is the full-text one and "
                         "the JSON says so (#258). A record found by meaning alone shares no word with "
                         "the task, so only `--decision floor` can brief it; under the calibrated "
                         "default the arm can only reorder what clears the line (REPORT §4w).")
    pk.add_argument("--rerank", nargs="?", const="on", choices=["on", "off"], default=None,
                    help="run a local cross-encoder over the first candidates and reorder them before "
                         "the gates (REPORT §4t); 'off' for the first-stage order. Omit it to follow the "
                         "config's `rerank` or OKL_RERANK. Needs the rerank extra and `okl embed` once "
                         "online; otherwise the first-stage order stands and the JSON says why.")
    pk.add_argument("--decision", choices=["floor", "calibrated", "tiered"], default=None,
                    help="how candidates become a briefing: 'calibrated' briefs those whose title, "
                         "symptom, aliases and triggers hold enough of the task's subject to clear a "
                         "line set on real subjectless prompts, at most five; 'floor' keeps those "
                         "sharing enough words with the task, up to the limit; 'tiered' (the default) "
                         "briefs what 'calibrated' briefs and lists the rest of what matched, one line "
                         "each, up to the limit (#291, REPORT §4w, §4y). Omit it to follow the "
                         "config's `decision` or OKL_DECISION.")
    pk.add_argument("--warm", choices=["on", "off"], default=None,
                    help="add what a lesson means to the calibrated line's score, from the local warm "
                         "model (`okl warm start`; REPORT §4z). When it does not answer, the briefing is "
                         "the model-free one and the JSON says why. Omit it to follow the config's `warm` "
                         "or OKL_WARM.")
    pk.add_argument("--near-misses", action="store_true", dest="near_misses",
                    help="append the records that matched the task and were left out (by the floor or "
                         "the cutoff) as id and title, at most twelve. A treatment under measurement "
                         "(REPORT §4s).")
    pk.add_argument("--index", action="store_true",
                    help="append every other lesson in scope as id and title, so the agent can fetch "
                         "one with `okl show <id>` when the briefing did not select it. A treatment "
                         "under measurement (REPORT §4r), about 120 characters per lesson.")
    pk.set_defaults(func=cmd_check)

    pe = sub.add_parser("embed", help="build or refresh the local vectors that --hybrid briefings "
                                       "fuse with the full-text search (needs the hybrid extra; "
                                       f"downloads {semantic.MODEL_ID} once). The model is fixed: "
                                       "check searches the vectors of that one model")
    pe.set_defaults(func=cmd_embed)

    pw = sub.add_parser("warm", help="the local process that keeps the briefing's model loaded, so a "
                                     "prompt can be briefed by meaning as well as words (needs the warm "
                                     "extra; REPORT §4z)")
    pw.add_argument("action", choices=["start", "stop", "status", "index", "serve"],
                    help="start it in the background, stop it, say whether it runs, embed this store's "
                         "lessons through it, or run it in the foreground")
    pw.add_argument("--wait", type=float, default=0.0, help="with start: seconds to wait for it to load")
    pw.set_defaults(func=cmd_warm)

    pr = sub.add_parser("record", help="record a node (defect/gate/claim/...)")
    pr.add_argument("--type", required=True); pr.add_argument("--title", required=True)
    pr.add_argument("--scope", required=True, help="'org' or 'repo:<name>' or 'repo'")
    pr.add_argument("--repo"); pr.add_argument("--body"); pr.add_argument("--status")
    pr.add_argument("--found-by", dest="found_by")
    pr.add_argument("--ttl-days", dest="ttl_days", type=int); pr.add_argument("--owner")
    pr.add_argument("--files", help="comma-sep path globs this node governs (enrolls it in drift detection)")
    pr.add_argument("--symptom", help="Symptom→Cause→Fix: the observable symptom (cause goes in --body)")
    pr.add_argument("--alias", action="append", dest="aliases", metavar="PHRASE",
                    help="the words a developer uses when this bites, repeatable (--alias 'logged out "
                         "on refresh' --alias 'session lost'); indexed like the symptom, so a prompt "
                         "in those words finds the lesson")
    pr.add_argument("--trigger", action="append", dest="triggers", metavar="PHRASING",
                    help="a whole phrasing of a moment the lesson applies, repeatable: the task you "
                         "were doing, the error you saw, other words for it, as typed before knowing "
                         "the lesson. The prompt or error that led to the lesson is the best one. "
                         "The calibrated briefing decision reads these (#291)")
    pr.add_argument("--fix", help="Symptom→Cause→Fix: the fix to apply")
    pr.add_argument("--applies-to", dest="applies_to", default=None,
                    help="stacks this lesson is VALID for (comma-sep), or 'any'. Leave unset "
                         "for a portable lesson — that is the default and the common case. "
                         "Use it only when the lesson genuinely does not transfer, e.g. a "
                         "framework's middleware ordering. Distinct from --tags, which "
                         "records subject and where the lesson was found.")
    pr.add_argument("--tags", help="comma-sep subject tags from the controlled vocabulary "
                    "(store.KNOWN_TAGS), e.g. 'react,security'")
    pr.add_argument("--id", help="a short stable id for a NEW lesson. An id that already exists "
                    "is refused: change that lesson with `okl update <id>`, which keeps its proof")
    pr.add_argument("--replace", action="store_true",
                    help="overwrite the lesson with this --id entirely, proof included (it keeps "
                         "only its first creation date); to refine one, use `okl update`")
    pr.add_argument("--verified", action="store_true",
                    help="refused: verify with `okl verify <id> --run ... --expect ...` instead")
    pr.set_defaults(func=cmd_record)

    pu = sub.add_parser("update", help="change fields of a lesson by id, keeping the rest and its proof")
    pu.add_argument("node_id", help="the lesson's id, as the briefing shows it in [brackets]")
    for flag in ("--type", "--title", "--scope", "--body", "--status", "--owner", "--symptom",
                 "--fix", "--tags"):
        pu.add_argument(flag)
    pu.add_argument("--found-by", dest="found_by")
    pu.add_argument("--alias", action="append", dest="aliases", metavar="PHRASE",
                    help="replace the lesson's aliases (repeatable); --alias \"\" clears them")
    pu.add_argument("--trigger", action="append", dest="triggers", metavar="PHRASING",
                    help="replace the lesson's triggers (repeatable); --trigger \"\" clears them")
    pu.add_argument("--ttl-days", dest="ttl_days", type=_days_or_blank)
    pu.add_argument("--applies-to", dest="applies_to")
    pu.add_argument("--files", help="changing the governed files clears the proof: a check of "
                                    "other files proves nothing about these")
    pu.epilog = ("Only the fields given change. An empty value (--fix \"\") clears an optional "
                 "field. The proof and the first creation date are kept unless --files changes.")
    pu.set_defaults(func=cmd_update)

    prt = sub.add_parser("retire", help="retire a lesson with a reason: wrong, replaced (--by) "
                                        "or obsolete; it is never deleted")
    prt.add_argument("node_id")
    prt.add_argument("--reason", required=True, help="why it is retired; kept with the lesson")
    how = prt.add_mutually_exclusive_group()
    how.add_argument("--by", help="the id of the lesson that replaces it: briefings then leave "
                                  "this one out and point to that one")
    how.add_argument("--obsolete", action="store_true",
                     help="its subject is gone: it is no longer briefed")
    prt.epilog = ("Without --by or --obsolete the lesson is wrong: it stays briefed as AVOID, so "
                  "nobody restates it as fact. A resolved defect is not retired; it keeps "
                  "briefing against its return.")
    prt.set_defaults(func=cmd_retire)

    psh = sub.add_parser("show", help="print one lesson by id, with its proof")
    psh.add_argument("node_id")
    psh.add_argument("--format", choices=["text", "json"], default="text")
    psh.set_defaults(func=cmd_show)

    ptg = sub.add_parser("triggers", help="list this store's own lessons that have no triggers, for an agent "
                                          "to draft them (REPORT §4x)")
    ptg.add_argument("node_id", nargs="?", help="only this lesson, if it has no triggers")
    ptg.add_argument("--format", choices=["text", "json"], default="text")
    ptg.set_defaults(func=cmd_triggers)

    prc = sub.add_parser(
        "recap", help="the lessons a session touched: briefed on, or whose files it changed",
        description="List the lessons this session was briefed on (read from a Claude Code "
                    "transcript) and those whose governed files it changed, with the commands "
                    "that act on them. The Stop hook adds this to its question. Prints nothing "
                    "when the session touched no lesson.")
    prc.add_argument("--transcript", help="the session's transcript (JSONL), as the Stop hook "
                     "receives its path")
    prc.add_argument("--since", help="when the session began: ISO 8601, or relative to now (90m, 6h, "
                     "2d); default: the transcript's first timestamp, and for --report without one, a day ago")
    prc.add_argument("--limit", type=int, default=5, help="briefed lessons to list (default 5)")
    prc.add_argument("--report", action="store_true",
                     help="how the session went: briefings, lessons recorded and retired, checks run "
                          "and failed, commits, and what is stale now, from the store's own logs (#279)")
    prc.add_argument("--format", choices=["text", "json"], default="text",
                     help="with --report: Markdown (default) or JSON")
    prc.set_defaults(func=cmd_recap)

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

    pm = sub.add_parser("metric", help="recurrence-after-arming, plus briefing exposure (lessons never shown, most shown unchecked)")
    pm.add_argument("--format", choices=["text", "json"], default="text")
    pm.set_defaults(func=cmd_metric)

    pdr = sub.add_parser("drift", help="source-vs-spec drift: rules whose governed code changed after verification")
    pdr.add_argument("--repo"); pdr.add_argument("--repo-dir", dest="repo_dir", default=".")
    pdr.add_argument("--gate", action="store_true", help="exit 1 if drift found, 2 if nothing could be checked (for CI and the pre-push hook)")
    pdr.add_argument("--format", choices=["text", "json"], default="text")
    pdr.add_argument("--snapshot", metavar="FILE",
                     help="read rules from a committed snapshot (okl export --drift) "
                          "instead of a store — for CI with no store")
    pdr.set_defaults(func=cmd_drift)

    pex = sub.add_parser("export", help="write the committed drift snapshot CI reads (okl-drift.json)")
    pex.add_argument("--drift", action="store_true", required=True,
                     help="the drift snapshot (the only export today; named so others can follow)")
    pex.add_argument("-o", "--output", help="path (default: okl-drift.json at the project root)")
    pex.add_argument("--allow-shrink", action="store_true",
                     help="write even when the committed snapshot is for another repo or holds rules "
                          "this store does not (refused otherwise, since they would leave CI's gate)")
    pex.set_defaults(func=cmd_export)

    pdoc = sub.add_parser("doctor", help="report other agent-memory tools installed beside okl, "
                                         "how they collide, and where drift is gated (changes nothing)")
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
    pd.add_argument("--refresh", action="store_true",
                    help="re-import only the records this store already holds, from the packs they came "
                         "from (their newer symptoms, aliases and text; verification is kept), without "
                         "importing the rest of each pack. With no path, finds the bundled packs from the "
                         "store's own seed ids; a repo's own pack file still has to be named.")
    pd.add_argument("--strict", action="store_true",
                    help="exit 2 instead of importing when an advice record has no symptom, a record is "
                         "trace-shaped, or an org record names one repository's paths or name "
                         "(for CI on a ledger repo)")
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
