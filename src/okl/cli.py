"""okl CLI — init / connect / check / record / search / seed / metric / serve.

Stdlib argparse only, so the package installs with zero required deps for the
local + client path. `serve` and `mcp` import their extras lazily.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import sys
from pathlib import Path

from . import core
from .client import Client, OKLUnreachableError, _find_config, load_config, save_config


def _print_json(obj) -> None:
    """Dump a result as indented JSON.

    The `--format json` path exists so other tools can consume a check without
    parsing the human briefing, which is markdown and free to change wording.
    """
    json.dump(obj, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _merge_hook_settings(claude: Path) -> bool:
    """Register both okl hooks in .claude/settings.json. Idempotent: existing settings and
    unrelated hooks are preserved; an already-registered okl hook is left alone. A hook
    that is installed but unregistered is a surface nobody runs."""
    settings_path = claude / "settings.json"
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except json.JSONDecodeError:
        print(f"! {settings_path} is not valid JSON — not touching it; register the hooks manually.")
        return False
    hooks_cfg = settings.setdefault("hooks", {})
    changed = False
    # UserPromptSubmit, not PreToolUse: only UserPromptSubmit/SessionStart stdout reaches the
    # model's context. A PreToolUse briefing fires but is never read (found by E2E test).
    wanted = [
        ("UserPromptSubmit", None, '"$CLAUDE_PROJECT_DIR"/.claude/hooks/userpromptsubmit-okl-check.sh'),
        ("Stop", None, '"$CLAUDE_PROJECT_DIR"/.claude/hooks/stop-okl-encode.sh'),
    ]
    for event, matcher, command in wanted:
        entries = hooks_cfg.setdefault(event, [])
        if any(h.get("command", "").endswith(Path(command).name)
               for e in entries for h in e.get("hooks", [])):
            continue
        entry: dict = {"hooks": [{"type": "command", "command": command}]}
        if matcher:
            entry["matcher"] = matcher
        entries.append(entry)
        changed = True
    if changed:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return changed


def cmd_init(args) -> int:
    """Wire the current repo so the loop runs without manual follow-up steps:
    config, hooks (installed AND registered), CI verifier, MCP registration.

    `--dry-run` prints every path it would touch and writes nothing. This command
    installs executable hooks and a CI workflow into your repo; you should be able
    to see that list before it happens."""
    import shutil
    if getattr(args, "dry_run", False):
        repo = args.repo or Path.cwd().name
        print(f"DRY RUN — nothing will be written. `okl init --repo {repo}` would:\n")
        print("  .okl/config.json                        repo name, interests, and the path to this okl")
        if Path(".claude").exists():
            print("  .claude/hooks/userpromptsubmit-okl-check.sh   executable; runs when you submit a task")
            print("  .claude/hooks/stop-okl-encode.sh             executable; runs when a session ends")
            print("  .claude/settings.json                   registers those two hooks (merged, existing keys kept)")
            print("  .mcp.json                               registers the okl MCP server (only if okl[mcp] is installed)")
        else:
            print("  (no .claude/ directory here, so no hooks would be installed)")
        if Path(".git").exists():
            print("  .github/workflows/okl-verify.yml        a CI workflow running the drift gate on PRs")
        else:
            print("  (not a git repository, so no CI workflow and no drift gate)")
        print("\nNothing is written outside this directory. Read the hooks before you register them:")
        print("  https://github.com/emeraldleaf/okl/blob/main/src/okl/scaffold/hooks/")
        return 0
    repo = args.repo or Path.cwd().name
    cfg = load_config()
    cfg["repo"] = repo
    if args.service:
        cfg["service_url"] = args.service
    if args.interests:
        cfg["interests"] = [t.strip().lower() for t in args.interests.split(",") if t.strip()]
    # Pin how to invoke okl on THIS machine, for hooks running outside the dev shell
    # (agent harnesses don't inherit venv/pipx PATH entries). Machine-local by design —
    # .okl/ is gitignored; hooks fall back to PATH and `python3 -m okl` regardless.
    cfg["okl_bin"] = shutil.which("okl") or f"{sys.executable} -m okl"
    path = save_config(cfg)
    print(f"✓ wrote {path}  (repo={repo}, mode={'remote' if cfg.get('service_url') else 'local'}"
          + (f", interests={','.join(cfg['interests'])}" if cfg.get("interests") else "") + ")")

    claude = Path(".claude")
    if claude.exists():
        _install_claude_wiring(claude)
    else:
        print("• no .claude/ dir here, so no hooks were installed. The store still works:")
        print("    - retrieval: `okl check --task \"...\"`, or the MCP server (`okl mcp`)")
        print("    - canon for any agent: `okl scaffold .` writes CLAUDE.md and AGENTS.md")
        print("    - the enforced pre-task read needs a hook, and okl auto-wires Claude Code only.")
        print("      The scripts in src/okl/scaffold/hooks/ are plain bash on stdin/stdout; if your")
        print("      agent has a pre-prompt hook, point it at them. Registration formats differ.")
    _install_ci_verifier()
    for line in _empty_store_guidance(Client()):
        print(line)
    # Said at install time, the one moment someone is reading okl's output and deciding
    # what to wire. Informational here: init succeeded; `okl doctor` is the re-runnable check.
    from . import coexist
    found = coexist.detect(Path.cwd(), Path.home())
    if found:
        print("\n" + coexist.render(found))
    return 0


def cmd_doctor(args) -> int:
    """Report agent-memory tools installed beside okl and how they collide (#40).

    Exit 1 when any is found -- a finding, per the CLI contract -- and 0 when none is.
    It reads settings files only and changes nothing.
    """
    from . import coexist
    cfg = _find_config()
    root = cfg.parent.parent if cfg else Path.cwd()
    found = coexist.detect(root, Path.home())
    print(coexist.render(found))
    return 1 if found else 0


def _install_claude_wiring(claude: Path) -> None:
    """Install AND register the hooks: the PreToolUse check (the enforced read) and the
    Stop encode reminder (the write-side catch). Scripts come from the packaged scaffold —
    one canonical source, no drift. Also registers the MCP server when the extra exists."""
    hooks = claude / "hooks"
    hooks.mkdir(exist_ok=True)
    scaffold_hooks = Path(__file__).parent / "scaffold" / "hooks"
    for name, label in [("userpromptsubmit-okl-check.sh", "pre-task check hook (UserPromptSubmit)"),
                        ("stop-okl-encode.sh", "encode reminder (Stop hook)")]:
        dst = hooks / name
        dst.write_text((scaffold_hooks / name).read_text())
        dst.chmod(0o755)
        print(f"✓ installed {label} → {dst}")
    if _merge_hook_settings(claude):
        print("✓ registered both hooks in .claude/settings.json (UserPromptSubmit + Stop)")
    else:
        print("• hooks already registered in .claude/settings.json")
    # MCP: register the okl server only if the extra is importable (a registration whose
    # dependency is missing would be a broken tool, worse than none).
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("• MCP extra not installed — `pip install 'observed-knowledge-ledger[mcp]'` then re-run init")
        print("  to register the agent tools. (The distribution is not named `okl`; PyPI refuses that.)")
        return
    mcp_path = Path(".mcp.json")
    mcp_cfg = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    servers = mcp_cfg.setdefault("mcpServers", {})
    if "okl" not in servers:
        servers["okl"] = {"command": "okl", "args": ["mcp"]}
        mcp_path.write_text(json.dumps(mcp_cfg, indent=2) + "\n")
        print("✓ registered okl MCP server → .mcp.json (okl_check / okl_record / okl_search)")


def _install_ci_verifier() -> None:
    """Install the CI verifier workflow instead of printing a copy instruction; warn
    loudly when git is absent, because the drift layer is dead without history."""
    if not Path(".git").exists():
        print("⚠ not a git repository — the drift verifier (okl drift) and the CI gate are DISABLED")
        print("  until `git init`: drift compares governed files against their last-verified commit.")
        return
    wf = Path(".github") / "workflows" / "okl-verify.yml"
    if wf.exists():
        print(f"• CI verifier already present → {wf}")
        return
    wf.parent.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).parent / "scaffold" / "ci" / "okl-verify.yml"
    wf.write_text(src.read_text())
    print(f"✓ installed CI verifier → {wf}  (drift gate + repo gates on every PR)")


def cmd_connect(args) -> int:
    """Point this repo at a shared service, and optionally store its token.

    Writing the token into .okl/config.json is a convenience for a laptop; CI and
    shared machines should pass OKL_TOKEN instead. save_config drops a .gitignore
    beside it so the secret cannot be committed either way.
    """
    cfg = load_config()
    cfg["service_url"] = args.url
    if args.token:
        cfg["token"] = args.token
    path = save_config(cfg)
    print(f"✓ connected → {args.url}  ({path})")
    return 0


def cmd_check(args) -> int:
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
    if args.format == "json":
        _print_json(result)
    elif args.format == "actions":
        # compact: the imperative list only, for small-context callers (subagents, CI)
        print(core.render_actions_only(result, limit=args.limit))
    else:
        print(core.render_check_for_agent(result))
    # stdout is what the UserPromptSubmit hook hands the agent; setup advice is for the
    # person, so it goes to stderr and never enters the agent's context. Skipped for json,
    # whose consumers parse the output.
    if args.format != "json" and result.get("store_records") == 0:
        for line in _empty_store_guidance(client):
            print(line, file=sys.stderr)
    return 0


def cmd_record(args) -> int:
    """Write one record to the store.

    Validation errors (an unknown tag, a malformed scope) are the caller's mistake and
    exit 2 with the message, which names the vocabulary. A traceback would bury the one
    line that tells them how to fix the call.
    """
    client = Client()
    kwargs = dict(type=args.type, title=args.title, scope=args.scope,
                  applies_to=getattr(args, "applies_to", None),
                  body=args.body, status=args.status, found_by=args.found_by,
                  ttl_days=args.ttl_days, owner=args.owner, verified=args.verified,
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


def cmd_link(args) -> int:
    """Join two records with a typed edge (e.g. a Gate CATCHES a Defect).

    Edges are what let a briefing say WHY a gate is armed rather than just naming it.
    """
    Client().link(args.src, args.rel, args.dst)
    print(f"✓ {args.src} -[{args.rel}]-> {args.dst}")
    return 0


def cmd_verify(args) -> int:
    """Run the named check, and stamp the node verified ONLY on an observed pass.

    The evidence trail (command, expect-match, timestamp) is stored on the node —
    the store-side mechanization of verify-before-claiming: no run, no stamp."""
    import subprocess
    from datetime import datetime, timezone
    r = subprocess.run(args.run, shell=True, capture_output=True, text=True,
                       timeout=args.timeout)
    output = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-5:])
    if r.returncode != 0:
        print(f"✗ check FAILED (exit {r.returncode}) — NOT stamping verification.\n{tail}",
              file=sys.stderr)
        return 1
    if args.expect and args.expect not in output:
        # exit 0 alone is a step grading itself — require the positive success signal
        # when the caller names one (the exit-0-zero-files lesson).
        print(f"✗ check exited 0 but expected signal {args.expect!r} NOT in output — NOT stamping.\n{tail}",
              file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    evidence = f"`{args.run}` exit 0" + (f", matched {args.expect!r}" if args.expect else "") + f" @ {stamp}"
    try:
        node = Client().verify(args.node_id, evidence)
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — check passed but the stamp was NOT recorded.\n{e}", file=sys.stderr)
        return 2
    print(f"✓ verified {node['id']} — {node['title']}\n  evidence: {node['verified_by']}")
    # Keep CI's view in step. A snapshot that exists is one CI reads, and re-verifying
    # without re-exporting leaves CI red for a rule that is green here -- the safe
    # direction, but a step everyone would forget. Only refreshed, never created.
    snap = _snapshot_path()
    if snap.exists():
        try:
            _write_snapshot(Client(), snap)
            print(f"  refreshed {snap.name} — commit it so CI sees this verification")
        except OKLUnreachableError as e:
            print(f"  ! {snap.name} NOT refreshed: {e}", file=sys.stderr)
    return 0


def _snapshot_path() -> Path:
    """Where the committed drift snapshot lives: the project root, found the way the
    config is, so running from a subdirectory neither misses it nor writes a second one."""
    from . import drift
    cfg = _find_config()
    return (cfg.parent.parent if cfg else Path.cwd()) / drift.SNAPSHOT_FILE


def _write_snapshot(client: Client, path: Path) -> int:
    from . import drift
    snap = drift.snapshot(client.all_nodes(), client.repo)
    path.write_text(drift.dump_snapshot(snap))
    return len(snap["rules"])


def cmd_export(args) -> int:
    """Write the committed drift snapshot CI reads when it has no store (issue #36)."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — nothing to export. Run `okl init`, `okl connect <url>`, "
              "or set OKL_DATABASE_URL.", file=sys.stderr)
        return 2
    path = Path(args.output) if args.output else _snapshot_path()
    try:
        n = _write_snapshot(client, path)
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — nothing exported.\n{e}", file=sys.stderr)
        return 2
    if n == 0:
        # An empty snapshot would make CI report NOTHING CHECKED, which is honest, but
        # committing one is almost certainly a mistake worth saying so about.
        print(f"wrote {path} with 0 rules — no rule in this store governs files "
              "(`okl record ... --files <globs>` enrolls one)", file=sys.stderr)
        return 2
    print(f"wrote {path}: {n} rule(s). Commit it — CI's drift gate reads the committed copy.")
    return 0


def cmd_search(args) -> int:
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


def cmd_metric(args) -> int:
    """Recurrence, with the coverage that makes the number readable (issue #31)."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — refusing to report a metric about a store that is not "
              "there. Run `okl init` or `okl connect <url>`.", file=sys.stderr)
        return 2
    try:
        report = client.recurrence_report()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot compute metric.\n{e}", file=sys.stderr)
        return 2
    if report is None:
        print("OKL: the connected service predates the coverage report, so this metric's "
              "coverage is unknown. Upgrade the service before reading it.", file=sys.stderr)
        return 2
    if args.format == "json":
        _print_json(report)
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
    return 0


def cmd_drift(args) -> int:
    """Source-vs-spec drift: rules whose governed code changed after last verification."""
    from . import drift
    client = Client()
    if args.snapshot:
        return _drift_from_snapshot(args, client)
    # Refused before any store is opened. Reading an unconfigured directory created an
    # empty okl.db as a side effect, found nothing in it, and printed OK -- which is what
    # CI saw on every run, because `okl init` gitignores the store (issue #21). `check`
    # has refused an unconfigured directory for the same reason since v0.2.
    if not client.configured:
        print("OKL NOT CONFIGURED — refusing to report drift. No store is named here: run "
              "`okl init`, `okl connect <url>`, or set OKL_DATABASE_URL.", file=sys.stderr)
        return 2
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot check drift.\n{e}", file=sys.stderr)
        return 2
    repo = args.repo or client.repo
    return _report_drift(args, drift.scan_drift(nodes, repo, repo_dir=args.repo_dir))


def _drift_from_snapshot(args, client: Client) -> int:
    """Drift against a committed snapshot instead of a store (issue #36).

    The snapshot is the store for a job that has none: CI without a service, and every
    fork PR. It names the store, so it answers `configured` on its own. An entry whose
    timestamp does not match its evidence refuses the whole run -- one hand-cleared rule
    would otherwise pass the gate while the rest of the report looked honest.
    """
    from . import drift
    try:
        snap = drift.read_committed_snapshot(args.snapshot, args.repo_dir)
    except ValueError as e:
        print(f"OKL SNAPSHOT REFUSED — {e}", file=sys.stderr)
        return 2
    nodes, problems = drift.nodes_from_snapshot(snap)
    if problems:
        print(f"OKL SNAPSHOT REFUSED — {len(problems)} entr(y/ies) cannot be trusted; re-run "
              "`okl verify` for each and re-export:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    repo = args.repo or snap.get("repo") or client.repo
    return _report_drift(args, drift.scan_drift(nodes, repo, repo_dir=args.repo_dir))


def _report_drift(args, scan) -> int:
    from . import drift
    hits, checked = scan
    if args.format == "json":
        _print_json({"drift": [h.as_dict() for h in hits], "count": len(hits),
                     "checked": checked})
    else:
        print(drift.render_drift(hits, checked))
    if not args.gate:
        return 0
    # Under --gate the exit code is the verdict, and it follows the CLI's contract:
    # 1 = ran and found drift, 2 = did not run. A gate that checked no rule did not run,
    # however clean its output looks.
    if hits:
        return 1
    return 2 if checked == 0 else 0


def cmd_dedup(args) -> int:
    """Report records that look like near-duplicates of each other.

    A review aid, never an auto-merge. Whether two similar records are "the same" is a
    judgment about intent, and the measured score bands for true paraphrases and for
    genuinely-distinct-but-related records overlap (see core.DEDUP_THRESHOLD). Deciding
    that automatically would delete real records.

    Duplicates are not merely untidy now that `check` applies a top-k cutoff: two records
    saying the same thing both get injected, spend the budget twice, and can push a third
    relevant record out of the briefing entirely.
    """
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — run `okl init` here, or `okl connect <url>`.", file=sys.stderr)
        return 2
    nodes = list(client.all_nodes())
    store = client._local_store() if client.mode == "local" else None
    idf = core._idf(store) if store is not None else {}

    seen: set[tuple[str, str]] = set()
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


def cmd_coverage(args) -> int:
    """Knowledge-to-code ratio — a health signal, not a target (Codified Context §4.2)."""
    import subprocess
    from pathlib import Path
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


def cmd_bootstrap(args) -> int:
    """Propose starter nodes from repo signals into a reviewable okl-bootstrap.json."""
    from pathlib import Path

    from . import bootstrap
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


def _bundled_seed_dir() -> Path:
    """Where the shipped seed packs live: the repo's seed/ in a checkout, or inside the
    installed package. Checked in that order so a clone exercises its own files."""
    repo_seed = Path(__file__).parent.parent.parent / "seed"
    return repo_seed if repo_seed.exists() else Path(__file__).parent / "seed"


def _pack_fits(pack_tags: set[str], interests: set[str]) -> bool:
    """Does a bundled pack fit a repo with these interests?

    A pack that names a stack fits only a repo that declared that stack; a pack with no
    stack fits on any shared subject. One shared subject is not enough on its own: the
    .NET packs carry `security` on a handful of records, so any-tag matching recommended
    109 .NET records to a repo that had declared `react, security`. That is REPORT §4d's
    mistake — reading a label on some records as a verdict on the whole — made at the
    point of import, where it is worse, because a pack imports every record at once.
    """
    tags = {t.lower() for t in pack_tags}
    stacks = tags & core.STACK_TAGS
    if stacks:
        return bool(stacks & interests)
    return bool(tags & interests)


def _empty_store_guidance(client: Client) -> list[str]:
    """What to do about an empty store, tailored to this repo. Empty list if not needed.

    Issue #27. Tailored rather than generic, because a list of commands is homework and
    the repo already knows enough to be specific: the bundled packs describe what they
    are about, and the repo declared its interests at init, so the packs that fit can be
    named with their sizes. It still imports nothing — cmd_seed explains why that must
    stay a deliberate choice.

    Only for a LOCAL store. A connected repo shares a service's store, which is neither
    "yours" to fill nor cheap to inspect from here.

    Emptiness is asked as "is there at least one record?" — a search capped at one row —
    rather than by loading every record to count them.
    """
    if client.mode == "remote":
        return []
    try:
        if client.search("", limit=1):
            return []
    except (OSError, OKLUnreachableError, ValueError, RuntimeError):
        return []

    lines = ["• this store is empty, so every check will say it proves nothing. To fill it:"]
    interests = {t.lower() for t in (client.interests or [])}
    packs = []
    for f in sorted(_bundled_seed_dir().glob("*.json")):
        count, tags = _describe_pack(f)
        if _pack_fits(tags, interests):
            packs.append((f, count))
    if packs:
        lines.append(f"    bundled packs that match your interests ({', '.join(sorted(interests))}):")
        # Quoted: the bundled dir is a checkout or an install path, and either can contain
        # a space, which splits a copied command into two arguments.
        lines += [f"      okl seed {shlex.quote(str(f))}    ({count} records)" for f, count in packs]
    elif interests:
        lines.append("    no bundled pack matches your interests; `okl seed` lists all of them")
    else:
        lines.append("    `okl seed` lists the bundled packs (declare interests with"
                     " `okl init --interests` and they are matched for you)")
    # Name the agent-driven route only where it exists. The seeding commands are stamped by
    # `okl scaffold`, possibly under a renamed .claude dir, and pointing at one that is not
    # installed sends the reader to a command their agent will not recognise.
    #
    # Resolved from the PROJECT ROOT, not the current directory. okl finds its config by
    # walking up, so `check` runs fine from a subdirectory — where a cwd-relative lookup
    # both missed a command installed at the root and advised `okl scaffold .`, which
    # would have stamped the whole kit into that subdirectory.
    cfg = _find_config()
    root = cfg.parent.parent if cfg else Path.cwd()
    if any(root.glob("*/commands/seed-from-codebase.md")):
        lines.append("    ask your agent to run /seed-from-codebase: it proposes cited records"
                     " from this repo's own code")
    else:
        rel = os.path.relpath(root, Path.cwd())
        lines.append(f"    `okl scaffold {shlex.quote(rel)}` adds /seed-from-codebase, which has"
                     " your agent propose cited records from this repo's own code")
    lines.append("    or write one yourself: okl record --type Rule --scope repo --title \"...\"")
    return lines


def _describe_pack(path: Path) -> tuple[int, set[str]]:
    """Count a pack's records and collect its subject tags, so the listing can say what
    a pack is ABOUT before anyone imports it."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0, set()
    tags: set[str] = set()
    for node in data.get("nodes", []):
        tags |= {t.strip() for t in (node.get("tags") or "").split(",") if t.strip()}
    return len(data.get("nodes", [])), tags


def cmd_seed(args) -> int:
    """Import seed packs — deliberately a choice, not a default.

    The bundled packs carry real rules from specific stacks. Importing all of them into
    an unrelated project fills its briefings with noise about frameworks it does not use,
    and because they are org-scoped that noise then reaches every connected repo. So a
    bare `okl seed` lists what is available and imports nothing; `--all` is the explicit
    opt-in.
    """

    from .seed import seed_from_file
    seed_dir = _bundled_seed_dir()
    interests = {t.lower() for t in (Client().interests or [])}

    if not args.path and not args.all:
        packs = sorted(str(f) for f in seed_dir.glob("*.json"))
        if not packs:
            print(f"no seed packs found under {seed_dir}")
            return 1
        print("Seed packs available (nothing has been imported):\n")
        for pk in packs:
            f = Path(pk)
            count, tags = _describe_pack(f)
            hit = " <- matches your interests" if _pack_fits(tags, interests) else ""
            print(f"  {f.name:38} {count:3} records  [{', '.join(sorted(tags)) or 'untagged'}]{hit}")
        print("\nThese hold real rules from specific stacks. Import the ones that match")
        print("your project rather than all of them:\n")
        print(f"  okl seed {seed_dir}/<pack>.json     one pack")
        print("  okl seed --all                        every pack above")
        if interests:
            print(f"\nThis repo declares: {', '.join(sorted(interests))}. Records tagged outside")
            print("those subjects stay filtered out of briefings even once imported.")
        else:
            print("\nTip: `okl init --interests \"<subjects>\"` filters what reaches a briefing.")
        return 0

    if args.all:
        targets = sorted(str(f) for f in seed_dir.glob("*.json"))
    else:
        path = Path(args.path)
        targets = sorted(str(f) for f in path.glob("*.json")) if path.is_dir() else [str(path)]
    if not targets:
        print(f"no seed files found at {args.path or seed_dir}")
        return 1

    client, total = Client(), 0
    for t in targets:
        n = seed_from_file(client, t)
        total += n
        print(f"  ✓ {n} record(s) from {Path(t).name}")
    print(f"✓ seeded {total} record(s) from {len(targets)} file(s)")
    if not interests:
        print("  Note: no interests declared, so any imported record can surface in any")
        print('  briefing here. `okl init --interests "<subjects>"` narrows that.')
    return 0


def cmd_scaffold(args) -> int:
    """Stamp the portable method kit (canon, skills, agent, commands, gates, evals, hook) into a repo."""
    from .scaffold_cmd import scaffold
    res = scaffold(target=args.target, repo=args.repo, force=args.force, plugin=args.plugin,
                   profile=args.profile)
    print(f"✓ scaffolded method kit into {res['root']}  (repo={res['repo']}"
          + (f", profiles={'+'.join(args.profile)}" if args.profile else "")
          + (", as Claude Code plugin" if res['plugin'] else "") + ")")
    print(f"  {len(res['written'])} file(s) written, {len(res['skipped'])} skipped (already existed).")
    if args.verbose:
        for f in res["written"]:
            print(f"    + {f}")
    if res["skipped"] and not args.force:
        print(f"  skipped (use --force to overwrite): {', '.join(res['skipped'][:8])}"
              + (" …" if len(res['skipped']) > 8 else ""))
    if res["fills"]:
        print(f"\n  {len(res['fills'])} <<FILL>> slot(s) to complete (stack-specific rules):")
        for f in res["fills"]:
            print(f"    • {f}")
        print("  grep -rn '<<FILL' . to find them all later.")
    print("\nNext: `okl init` to wire the knowledge layer, then `/feature-spec` before your first change.")
    return 0


def cmd_serve(args) -> int:
    """Run the shared HTTP service.

    The 0.0.0.0 default is so the service is reachable from outside its container,
    which is the only way a shared instance is useful. OKL_TOKEN gates every route
    except /health; see docs/DEPLOY.md before exposing it.
    """
    from .service import run
    run(host=args.host, port=args.port)
    return 0


def cmd_mcp(args) -> int:
    """Serve the MCP tool surface over stdio, for a coding agent to call.

    Same operations as the CLI through the same Client, so remote/local mode and the
    fail-closed behaviour are identical whichever surface the agent uses.
    """
    from .mcp_server import run_stdio
    run_stdio()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree for every subcommand.

    One long declarative function on purpose: the parser IS the CLI's contract, and a
    reader answering "what flags does verify take" should find the whole answer in one
    place rather than following a chain of registration helpers.
    """
    p = argparse.ArgumentParser(prog="okl", description="Observed Knowledge Ledger — lessons your coding agents can trust, proven by checks.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="wire the current repo (config + hook + CI pointer)")
    pi.add_argument("--repo"); pi.add_argument("--service")
    pi.add_argument("--interests", help="comma-sep subject tags this repo cares about "
                    "(filters org-scope lessons in `check`; see store.KNOWN_TAGS)")
    pi.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="list every file init would write or modify, and write nothing")
    pi.set_defaults(func=cmd_init)

    pc = sub.add_parser("connect", help="point this repo at a shared OKL service URL")
    pc.add_argument("url"); pc.add_argument("--token")
    pc.set_defaults(func=cmd_connect)

    pk = sub.add_parser("check", help="pre-task read: relevant lessons for a task")
    pk.add_argument("--task", required=True); pk.add_argument("--repo")
    pk.add_argument("--format", choices=["agent", "actions", "json"], default="agent",
                    help="agent: the full briefing. actions: the routed action list only, "
                         "for callers on a small context budget. json: the raw result.")
    pk.add_argument("--limit", type=int, default=None,
                    help="cap how many records the briefing draws on (and how many actions "
                         "'--format actions' prints). Use with subagents on a token budget.")
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
    pr.add_argument("--verified", action="store_true")
    pr.set_defaults(func=cmd_record)

    pl = sub.add_parser("link", help="add an edge between two nodes")
    pl.add_argument("src"); pl.add_argument("rel"); pl.add_argument("dst")
    pl.set_defaults(func=cmd_link)

    pvf = sub.add_parser("verify", help="run a check and stamp a node verified only on an observed pass")
    pvf.add_argument("node_id")
    pvf.add_argument("--run", required=True, help="the check command; exit 0 required to stamp")
    pvf.add_argument("--expect", help="substring that must appear in the output — a positive success "
                     "signal, so exit 0 alone can't self-certify (the exit-0-zero-files lesson)")
    pvf.add_argument("--timeout", type=int, default=600, help="seconds before the check is killed (default 600)")
    pvf.set_defaults(func=cmd_verify)

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
    psc.add_argument("--plugin", action="store_true", help="also write plugin.json (Claude Code plugin)")
    from .scaffold_cmd import list_profiles
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


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch, converting store errors into exit codes.

    The backstop matters more than it looks: this CLI runs inside other people's hooks
    and CI, where the exit code is the only thing read. No command may answer a
    rejected or unreachable store with a traceback and a zero exit.
    """
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OKLUnreachableError) as e:
        # The backstop, so no command can ever answer a rejected or unreachable service
        # with a Python traceback. Commands that can say something more specific catch
        # these themselves and never reach here; this exists so the ones that do not —
        # and the ones added later — still exit non-zero with a line a human can act on.
        print(f"OKL: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
