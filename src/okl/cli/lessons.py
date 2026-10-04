"""Reading and writing lessons: `okl check`, `record`, `link`, `search`, `bootstrap`, `dedup`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .. import core
from ..client import Client, OKLUnreachableError
from .common import _print_json
from .packs import _empty_store_guidance


def _briefing_text(result: dict[str, Any], args: argparse.Namespace) -> str:
    """The briefing for the agent: in full, or only its action list under --compact."""
    if args.compact:
        return core.render_actions_only(result, limit=args.limit)
    return core.render_check_for_agent(result)


def cmd_check(args: argparse.Namespace) -> int:
    """Print the lessons that apply to `--task`, in the shape `--format` names.

    Exit 0 when the check ran, even if nothing applies; 2 when it could not run (no
    config, an unreachable store, or a rejected request), so a hook never reads a
    failure as a clean check.
    """
    client = Client()
    if not client.configured:
        # FAIL CLOSED. Without a config there is no store to read; proceeding would
        # create an empty database here and then report a clean check against it —
        # "no rules apply" when the truth is "nothing was ever asked".
        print("OKL NOT CONFIGURED — refusing to report a clean check.\n"
              "No .okl/config.json in this directory or any parent, and no OKL_SERVICE_URL.\n"
              "Run `okl init` here, or `okl connect <url>` to point at a shared store.",
              file=sys.stderr)
        return 2
    # An explicit --interests overrides the repo's configured list for this one call.
    # `--interests ""` means "no filtering", which is distinct from omitting the flag
    # (use the config). The eval harness needs this: inheriting the host repo's interests
    # made one of its tasks silently measure the absence of the rule it tests.
    # getattr, not attribute access: tests and library callers construct a Namespace by
    # hand with only the fields they care about, and a command handler that assumes the
    # full argparse surface breaks for every caller that is not the parser.
    override = getattr(args, "interests", None)
    if override is not None:
        client.interests = [t.strip().lower() for t in override.split(",") if t.strip()]
    try:
        result = client.check(args.task, repo=args.repo, limit=args.limit)
    except OKLUnreachableError as e:
        # FAIL CLOSED — loud, non-zero, no reassuring empty result.
        print(f"OKL UNREACHABLE — refusing to report a clean check.\n{e}", file=sys.stderr)
        return 2
    except ValueError as e:
        # A 4xx (usually a 401 against a token-protected service) is a REFUSED check,
        # not a clean one, so it fails closed just the same. It gets its own message
        # because the fix is different: a credential, not connectivity. Before this,
        # an unauthorized check exited 0 with a raw urllib traceback.
        print(f"OKL REFUSED THE CHECK — refusing to report a clean check.\n{e}", file=sys.stderr)
        return 2
    if args.format == "hook":
        # What a Claude Code UserPromptSubmit hook prints: the briefing into the model's
        # context, and one line the person can see. OKL_QUIET=1 keeps the line out.
        out: dict[str, Any] = {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _briefing_text(result, args)}}
        notice = None if os.environ.get("OKL_QUIET") == "1" else core.briefing_notice(result)
        if notice:
            out["systemMessage"] = notice
        print(json.dumps(out))
        return 0
    if args.format == "json":
        _print_json(result)
    elif args.format == "actions":
        # compact: the imperative list only, for small-context callers (subagents, CI)
        print(core.render_actions_only(result, limit=args.limit))
    else:
        print(_briefing_text(result, args))
    # stdout is what the UserPromptSubmit hook hands the agent; setup advice is for the
    # person, so it goes to stderr and never enters the agent's context. Skipped for json,
    # whose consumers parse the output.
    if args.format != "json" and result.get("store_records") == 0:
        for line in _empty_store_guidance(client):
            print(line, file=sys.stderr)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """Write one record to the store.

    Validation errors (an unknown tag, a malformed scope) are the caller's mistake and
    exit 2 with the message, which names the vocabulary. A traceback would bury the one
    line that tells them how to fix the call.
    """
    if args.verified:
        # A stamp the recorder awards itself is the step grading its own homework. The
        # README said live verification refused this; it accepted it, silently, and the
        # shipped encoding-loop skill told agents to pass it. Found checking a launch post
        # that claimed "never by assertion". Historical receipts still import via `okl seed`.
        print("okl record --verified is refused: a lesson is verified by running a check, not "
              "by saying so.\n  Record it without --verified, then run `okl verify <id>` to see the "
              "tests that touch its files, or ask your agent to prove it.\n  (Importing historical, "
              "already-verified records? Use okl seed.)", file=sys.stderr)
        return 2
    client = Client()
    kwargs = dict(type=args.type, title=args.title, scope=args.scope,
                  applies_to=getattr(args, "applies_to", None),
                  body=args.body, status=args.status, found_by=args.found_by,
                  ttl_days=args.ttl_days, owner=args.owner,
                  files=args.files, symptom=args.symptom, fix=args.fix, tags=args.tags,
                  id=args.id)
    if args.repo:
        kwargs["repo"] = args.repo
    try:
        node_id = client.record(**{k: v for k, v in kwargs.items() if v is not None})
    except ValueError as e:
        # An unknown tag or a malformed scope is the caller's mistake, and the exception
        # text names the vocabulary they need. A traceback buries that under a stack.
        print(f"NOT RECORDED — {e}", file=sys.stderr)
        return 2
    except OKLUnreachableError as e:
        print(f"NOT RECORDED — {e}", file=sys.stderr)
        return 2
    print(node_id)
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    """Join two records with a typed edge (e.g. a Gate CATCHES a Defect).

    Edges are what let a briefing say WHY a gate is armed rather than just naming it.
    """
    Client().link(args.src, args.rel, args.dst)
    print(f"✓ {args.src} -[{args.rel}]-> {args.dst}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Free-text search across the encoded body.

    Distinct from `check`: search answers "what do we know about X", check answers
    "what applies to the task I am about to start" and applies scope, interest and
    cutoff filtering on the way.
    """
    client = Client()
    # A wrong --scope used to return an empty list and exit 0, which reads as "this repo
    # has learned nothing" when it actually means "you typed the scope wrong". `--scope
    # repo` is the obvious guess and silently found nothing, because the stored form is
    # `repo:<name>`. Reporting an empty result and a misspelling identically is the
    # silence-as-safety failure `check` already refuses to make about an empty store.
    scope = args.scope
    if scope:
        if scope in ("repo", "local", "this"):
            scope = f"repo:{client.repo}"          # shorthand: the configured repo
        elif scope != "org" and not (scope.startswith("repo:") and scope[5:].strip()):
            print(f"REFUSING: --scope {scope!r} is not a scope. Use 'org', 'repo:<name>', "
                  f"or 'repo' for this repo ({client.repo}).", file=sys.stderr)
            return 2
    results = client.search(args.query, scope=scope,
                            node_types=args.type, limit=args.limit)
    # A well-formed scope naming a repo the store has never heard of is almost certainly a
    # typo, and returns the same empty list as a real repo that has recorded nothing yet.
    # Distinguish them the way `check` distinguishes "no rules apply" from "empty store" —
    # a warning, never a refusal, because a fresh repo legitimately has no records.
    if not results and scope and scope.startswith("repo:"):
        known = sorted({n["scope"] for n in client.search("", limit=10_000)
                        if n["scope"].startswith("repo:")})
        if known and scope not in known:
            print(f"note: no record anywhere carries scope {scope!r}. The store knows "
                  f"{', '.join(known)} — check for a typo.", file=sys.stderr)
    if args.format == "json":
        _print_json(results)
    else:
        for r in results:
            tag = " (STALE)" if r.get("stale") else ""
            print(f"[{r['type']:10}] {r['scope']:16} {r['title']}{tag}")
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    """Report records that look like near-duplicates of each other.

    A review aid, never an auto-merge. Whether two similar records are "the same" is a
    judgment about intent, and the measured score bands for true paraphrases and for
    genuinely-distinct-but-related records overlap (see core.DEDUP_THRESHOLD). Deciding
    that automatically would delete real records.

    Duplicates are not merely untidy now that `check` applies a top-k cutoff: two records
    saying the same thing both get injected, spend the budget twice, and can push a third
    relevant record out of the briefing entirely.

    Exit 1 when it finds candidate pairs, 0 when it finds none, 2 when okl is not
    configured here.
    """
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — run `okl init` here, or `okl connect <url>`.", file=sys.stderr)
        return 2
    nodes = list(client.all_nodes())
    store = client._local_store() if client.mode == "local" else None
    idf = core._idf(store) if store is not None else {}

    seen: set[tuple[str, ...]] = set()
    pairs = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            score = core.duplicate_score(a, b, idf)
            if score >= args.threshold:
                key = tuple(sorted((a.id, b.id)))
                if key not in seen:
                    seen.add(key)
                    pairs.append((score, a, b))
    pairs.sort(key=lambda p: -p[0])

    if not pairs:
        print(f"OKL dedup: OK — no pair of the {len(nodes)} records scores at or above "
              f"{args.threshold}.")
        return 0

    print(f"OKL dedup: {len(pairs)} candidate pair(s) at or above {args.threshold}, "
          f"out of {len(nodes)} records.\n"
          "These are candidates for a human to rule on, not confirmed duplicates.\n")
    for score, a, b in pairs[: args.limit]:
        print(f"  {score:.2f}")
        for n in (a, b):
            print(f"    [{n.id}] {n.type} · {n.scope}")
            print(f"       {n.title}")
            if n.symptom:
                print(f"       symptom: {n.symptom[:88]}")
        print()
    if len(pairs) > args.limit:
        print(f"  ... {len(pairs) - args.limit} more (raise --limit)")
    print("Resolve by deciding which record is the one to keep, then RETRACT or link the\n"
          "other with SUPERSEDES — deleting loses the record that it was once believed.")
    return 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Propose starter nodes from repo signals into a reviewable okl-bootstrap.json."""
    from .. import bootstrap
    repo = args.repo or Client().repo
    proposal = bootstrap.propose_nodes(repo, repo_dir=args.repo_dir)
    out = Path(args.out)
    out.write_text(json.dumps(proposal, indent=1))
    n = len(proposal["nodes"])
    print(f"✓ proposed {n} starter record(s) → {out}")
    if n == 0:
        print("  Nothing found. This command reads only git history and file names, so it")
        print("  comes up empty on young repos and on ones whose history is uninformative.")
    print("  Review + edit (set scope, add symptom/cause/fix, delete noise), then:")
    print(f"    okl seed {out}")
    print("\n  Better: ask your coding agent to run /seed-from-codebase (stamped by")
    print("  `okl scaffold`). It reads the code itself — the guard rails, the CI config,")
    print("  the fix commits — and proposes records with a file:line citation each.")
    return 0
