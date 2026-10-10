"""Proving lessons and noticing stale ones: `okl verify`, `reverify`, `drift` and `export`.

A lesson is verified only by a check that was seen to pass, and the commit it passed at
is recorded, so drift can tell when the files it governs have changed since.
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..client import Client, OKLNoAnswerError, OKLUnreachableError, _find_config
from .common import _print_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..drift import DriftHit
    from ..store import Node


def _run_check(args: argparse.Namespace) -> str | None:
    """Run `--run` and return its output if it passed, or None after saying why it did not.

    Passing means exit 0 and, when `--expect` is given, that text in the output: exit 0
    alone is a step grading itself (the exit-0-zero-files lesson).
    """
    import subprocess
    try:
        r = subprocess.run(args.run, shell=True, capture_output=True, text=True,
                           timeout=args.timeout)
    except subprocess.TimeoutExpired:
        # Uncaught, one slow check ended `okl reverify` in a traceback and left every
        # later lesson unchecked (CodeRabbit on #79). A timeout is a failed check.
        print(f"✗ check TIMED OUT after {args.timeout}s — NOT stamping verification.",
              file=sys.stderr)
        return None
    output = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-5:])
    if r.returncode != 0:
        print(f"✗ check FAILED (exit {r.returncode}) — NOT stamping verification.\n{tail}",
              file=sys.stderr)
        return None
    if args.expect and args.expect not in output:
        print(f"✗ check exited 0 but expected signal {args.expect!r} NOT in output — NOT stamping.\n{tail}",
              file=sys.stderr)
        return None
    return output


def cmd_verify(args: argparse.Namespace) -> int:
    """Run the named check, and stamp the node verified ONLY on an observed pass.

    The evidence trail (command, expect-match, timestamp) is stored on the node —
    the store-side mechanization of verify-before-claiming: no run, no stamp."""
    from datetime import datetime, timezone
    # Before anything runs: with no store, the check's result could not be recorded, and
    # running it anyway executed the user's command and reported its failure as a finding.
    if not Client().configured:
        print("OKL: not configured: no store to record a verification in, so the check was "
              "not run. Run `okl init` here, or `okl connect <url>`.", file=sys.stderr)
        return 2
    if not args.run:
        return _suggest_check(args.node_id)
    if _run_check(args) is None:
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    # The commit the check passed at: drift diffs the governed files there against HEAD
    # instead of comparing clocks (#102). It goes into the evidence before the stamp, which
    # binds it in the committed snapshot and keeps older okl versions able to read it.
    root = _snapshot_path().parent
    commit = _head_commit(root)
    evidence = (f"`{args.run}` exit 0" + (f", matched {args.expect!r}" if args.expect else "")
                + (f" on commit {commit[:12]}" if commit else "") + f" @ {stamp}")
    try:
        node = Client().verify(args.node_id, evidence, commit=commit)
    except OKLNoAnswerError as e:
        # The stamp was sent before the answer was lost, so it may be stored; saying it was
        # not would be a guess. A second stamp of the same lesson does no harm.
        print("OKL DID NOT ANSWER — check passed, and the service may have recorded the stamp; "
              f"running this verify again is safe.\n{e}", file=sys.stderr)
        return 2
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — check passed but the stamp was NOT recorded.\n{e}", file=sys.stderr)
        return 2
    print(f"✓ verified {node['id']} — {node['title']}\n  evidence: {node['verified_by']}")
    dirty = _uncommitted(root, node.get("files")) if commit else []
    if dirty:
        # The check saw these edits, but the stamp is the commit without them, so the lesson
        # reads as changed the moment they are committed. Commit first, then verify.
        print(f"  ! uncommitted changes to {', '.join(dirty[:3])}{' …' if len(dirty) > 3 else ''}: "
              "commit them, then verify again, or this lesson will show as drifted",
              file=sys.stderr)
    _refresh_snapshot(node)
    if getattr(args, "branch_warning", True):
        _warn_off_branch(Client(), skip=node["id"])
    return 0


def _refresh_snapshot(node: dict) -> None:
    """After a passing verify: create or refresh the committed drift snapshot CI reads."""
    # Keep CI's view in step. A snapshot that exists is one CI reads, and re-verifying
    # without re-exporting leaves CI red for a rule that is green here -- the safe
    # direction, but a step everyone would forget. The FIRST snapshot is created here too,
    # when the verified lesson governs files: it used to need a separate `okl export
    # --drift` that the getting-started guide had to teach as a trap. Never for a lesson
    # without files -- a snapshot of zero rules is one CI rightly reads as broken.
    snap = _snapshot_path()
    if _no_ci_reads(snap):
        # #114: with no CI workflow, a snapshot nobody committed is read by nothing, and
        # creating one left an untracked file after every verify. A committed one is still
        # refreshed: another CI or a hook may run the gate against it.
        if node.get("files") and not snap.exists():
            print(f"  (no {snap.name} written: no CI workflow here. If another CI runs the "
                  "gate, `okl export --drift` once and commit it)")
        return
    if snap.exists() or node.get("files"):
        try:
            existed = snap.exists()
            _write_snapshot(Client(), snap)
            print(f"  {'refreshed' if existed else 'created'} {snap.name} — commit it so CI sees this verification")
        except OKLUnreachableError as e:
            print(f"  ! {snap.name} NOT refreshed: {e}", file=sys.stderr)


def _warn_off_branch(client: Client, skip: str | None = None) -> None:
    """Name, on stderr, the lessons whose stamps sit on another branch's commit (#126).

    One store serves every branch, so a lesson verified on a sibling branch carries that
    branch's commit here, and the snapshot written on this branch commits it. Said where
    the snapshot is written, `okl verify` and `okl export --drift`, so nobody learns of it
    from a red build on a branch whose files never changed.
    """
    from .. import drift
    try:
        items = drift.off_branch(client.all_nodes(), client.repo, str(_snapshot_path().parent))
    except OKLUnreachableError:
        return
    items = [(n, c) for n, c in items if n.id != skip]
    if items:
        print(drift.render_off_branch(items).lstrip("\n"), file=sys.stderr)


_GENERIC_STEMS = {"src", "lib", "app", "main", "index", "test", "tests", "pages", "utils", "util",
                  "init", "__init__", "core", "common", "components", "styles", "docs", "readme"}


def _tests_touching(root: Path, files: str | None, limit: int = 5) -> list[str]:
    """Tracked test files that mention a governed file by name: the likeliest checks."""
    import subprocess
    stems = set()
    for glob in (files or "").split(","):
        name = glob.strip().rstrip("/").rsplit("/", 1)[-1]
        stem = name.split(".")[0]
        if len(stem) >= 4 and not any(c in stem for c in "*?[") and stem.lower() not in _GENERIC_STEMS:
            stems.add(stem)
    if not stems:
        return []
    listed = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True)
    tests = [p for p in listed.stdout.splitlines()
             if any(t in p.lower() for t in ("test", "spec"))][:2000]
    if not tests:
        return []
    args = ["git", "-C", str(root), "grep", "-l", "-I", "-F"]
    for s in sorted(stems):
        args += ["-e", s]
    found = subprocess.run([*args, "--", *tests], capture_output=True, text=True)
    return found.stdout.splitlines()[:limit]


def _suggest_check(node_id: str) -> int:
    """`okl verify <id>` with no --run: what the lesson says, the files it covers, and the
    tests that already mention them -- the parts a person has to supply, found for them.

    The three-part command was the step people could not fill in ("how am I supposed to
    know them?"); this answers it from the store and the repo. Exit 2: nothing was stamped.
    """
    client = Client()
    try:
        node = next((n for n in client.all_nodes() if n.id == node_id), None)
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot look the lesson up.\n{e}", file=sys.stderr)
        return 2
    if node is None:
        print(f"no lesson with id {node_id!r}. `okl drift` and the briefing show ids in brackets.",
              file=sys.stderr)
        return 2
    print(f"[{node.id}] {node.title}")
    if node.symptom:
        print(f"  when you see: {node.symptom}")
    if node.fix:
        print(f"  the lesson says: {node.fix}")
    root = _snapshot_path().parent
    if node.files:
        print(f"  covers: {node.files}")
        tests = _tests_touching(root, node.files)
        if tests:
            print("\nTests that mention those files, the likeliest checks:")
            for t in tests:
                print(f"  {t}")
            # Quoted, because the user pastes this and `okl verify --run` hands it to a shell:
            # a tracked test file named `a; rm -rf x.py` must arrive as one argument.
            run = (f"pytest -q {shlex.quote(tests[0])}" if tests[0].endswith(".py")
                   else "<the command that runs that test>")
            print(f"\nIf one of them fails when the lesson is broken, prove the lesson with it:\n"
                  f"  okl verify {shlex.quote(node.id)} --run {shlex.quote(run)} --expect passed")
        else:
            # A search miss, not proof: a test can cover a lesson by driving the command
            # without ever naming the file.
            print("\nNo test mentions those files by name. One may still cover the lesson by driving\n"
                  "the command instead, so look for it before writing a new check.")
    print("\nOr ask your agent to prove it: it reads the lesson, finds or writes a test that fails\n"
          "when the lesson is broken, runs it, and records the result. Nothing was stamped.")
    return 2


def _head_commit(root: Path) -> str | None:
    """HEAD's full commit name for the repository at `root`, or None outside git."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", "HEAD"],
                             capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", sha) else None


def _uncommitted(root: Path, files: str | None) -> list[str]:
    """Governed paths with uncommitted changes, as git reports them (empty when clean)."""
    import subprocess
    specs = [g.strip() for g in (files or "").split(",") if g.strip()]
    if not specs:
        return []
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *specs],
                             capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line[3:] for line in out.stdout.splitlines() if len(line) > 3] if out.returncode == 0 else []


def _stored_check(verified_by: str | None) -> tuple[str, str | None] | None:
    """The command and expected signal `okl verify` recorded, or None if there is none
    (never verified, or stamped by an import that carried no evidence)."""
    import ast
    if not verified_by or not verified_by.startswith("`"):
        return None
    end = verified_by.rfind("` exit 0")
    if end <= 0:
        return None
    run = verified_by[1:end]
    rest = verified_by[end + len("` exit 0"):]
    expect = None
    if rest.startswith(", matched "):
        lit = rest[len(", matched "):].rsplit(" @ ", 1)[0]
        lit = re.sub(r" on commit [0-9a-f]{7,64}$", "", lit)   # the commit #102 records
        try:
            expect = ast.literal_eval(lit)
        except (ValueError, SyntaxError):
            return None
    return run, expect


def _reverify_permitted(args: argparse.Namespace, planned: bool, manual: bool) -> int | None:
    """None to go ahead and run the listed commands, or the exit code to stop with."""
    if not planned or getattr(args, "dry_run", False):
        return 1 if (manual or planned) else 0
    if args.yes:
        return None
    if not sys.stdin.isatty():
        print("refusing to run stored commands unattended: review them above, then pass --yes",
              file=sys.stderr)
        return 2
    return None if input("Run them? [y/N] ").strip().lower() in ("y", "yes") else 2


def cmd_reverify(args: argparse.Namespace) -> int:
    """Re-run the stored check of every drifted lesson and re-stamp the ones that pass.

    `okl verify` already records the exact command and expected signal as evidence, so a
    drifted lesson's re-check is known. Retyping each one was the step that made drift
    upkeep a chore (issue #63). The commands come from the STORE, which on a shared
    service holds records other people wrote, so they are listed and run only after a
    confirmation or --yes: stored data reaching a shell unasked is how a shared store
    becomes remote code execution.
    """
    from .. import drift
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — nothing to re-verify. Run `okl init` first.", file=sys.stderr)
        return 2
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot re-verify.\n{e}", file=sys.stderr)
        return 2
    by_id = {n.id: n for n in nodes}
    root = str(_snapshot_path().parent)
    hits, _ = drift.scan_drift(nodes, client.repo, repo_dir=root)
    # A lesson last checked on another branch is re-checked here too, even when its files
    # still match: re-stamping it on this branch is the fix the drift report points to (#126).
    targets = [(h.node_id, h.title) for h in hits]
    targets += [(n.id, n.title) for n, _c in drift.off_branch(nodes, client.repo, root)
                if n.id not in {h.node_id for h in hits}]
    if not targets:
        print("okl reverify: nothing has drifted.")
        return 0
    plan, manual = [], []
    for nid, title in targets:
        chk = _stored_check(by_id[nid].verified_by)
        (plan.append((nid, chk)) if chk else manual.append((nid, title)))
    for nid, title in manual:
        print(f"• [{nid}] {title}\n    no stored check yet: ask your agent to write one, or run "
              f"`okl verify {nid}` to see the tests that touch its files")
    if plan:
        print(f"okl reverify will run {len(plan)} stored check(s), from the store:")
        for nid, (run, _exp) in plan:
            print(f"  [{nid}] {run}")
    stop = _reverify_permitted(args, bool(plan), bool(manual))
    if stop is not None:
        return stop
    failed = 0
    for nid, (run, exp) in plan:
        rc = cmd_verify(argparse.Namespace(node_id=nid, run=run, expect=exp, timeout=args.timeout,
                                           branch_warning=False))
        failed += rc != 0
    print(f"okl reverify: {len(plan) - failed} re-verified, {failed} failed, {len(manual)} need a first check.")
    _warn_off_branch(client)
    return 1 if (failed or manual) else 0


def _snapshot_path() -> Path:
    """Where the committed drift snapshot lives: the project root, found the way the
    config is, so running from a subdirectory neither misses it nor writes a second one."""
    from .. import drift
    cfg = _find_config()
    return (cfg.parent.parent if cfg else Path.cwd()) / drift.SNAPSHOT_FILE


def _no_ci_reads(snap: Path) -> bool:
    """True when nothing will read `snap`: init recorded no CI workflow ("ci": false) and
    the snapshot is not committed. Committed means tracked by git, not present on disk:
    an untracked copy is exactly the clutter #114 is about."""
    import json
    import subprocess
    cfg = _find_config()
    try:
        ci_off = cfg is not None and json.loads(cfg.read_text()).get("ci") is False
    except (OSError, ValueError, AttributeError):
        return False   # unreadable config: keep the old behaviour, which writes
    if not ci_off:
        return False
    try:
        tracked = subprocess.run(["git", "-C", str(snap.parent), "ls-files", "--error-unmatch",
                                  snap.name], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        tracked = False
    return not tracked


def _write_snapshot(client: Client, path: Path) -> int:
    from .. import drift
    snap = drift.snapshot(client.all_nodes(), client.repo)
    path.write_text(drift.dump_snapshot(snap))
    return len(snap["rules"])


def cmd_export(args: argparse.Namespace) -> int:
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
    _warn_off_branch(client)
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    """Source-vs-spec drift: rules whose governed code changed after last verification."""
    from .. import drift
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
    return _report_drift(args, drift.scan_drift(nodes, repo, repo_dir=args.repo_dir),
                         drift.governs_nothing(nodes, repo, args.repo_dir),
                         drift.off_branch(nodes, repo, args.repo_dir))


def _drift_from_snapshot(args: argparse.Namespace, client: Client) -> int:
    """Drift against a committed snapshot instead of a store (issue #36).

    The snapshot is the store for a job that has none: CI without a service, and every
    fork PR. It names the store, so it answers `configured` on its own. An entry whose
    timestamp does not match its evidence refuses the whole run -- one hand-cleared rule
    would otherwise pass the gate while the rest of the report looked honest.
    """
    from .. import drift
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
    return _report_drift(args, drift.scan_drift(nodes, repo, repo_dir=args.repo_dir),
                         drift.governs_nothing(nodes, repo, args.repo_dir),
                         drift.off_branch(nodes, repo, args.repo_dir))


def _report_drift(args: argparse.Namespace, scan: tuple[list[DriftHit], int],
                  missing: Sequence[Node] = (),
                  elsewhere: Sequence[tuple[Node, str]] = ()) -> int:
    from .. import drift
    hits, checked = scan
    # Lessons watching files that are gone are reported beside the drift, never as drift:
    # the exit code is unchanged, because what to do with them is a decision (#109). So
    # are lessons last checked on another branch whose files still match (#126); one whose
    # files differ is drift already, and its reason says where it was checked.
    elsewhere = [(n, c) for n, c in elsewhere if n.id not in {h.node_id for h in hits}]
    if args.format == "json":
        _print_json({"drift": [h.as_dict() for h in hits], "count": len(hits),
                     "checked": checked,
                     "governs_nothing": [{"node_id": n.id, "title": n.title, "files": n.files}
                                         for n in missing],
                     "off_branch": [{"node_id": n.id, "title": n.title, "verified_commit": c}
                                    for n, c in elsewhere]})
    else:
        print(drift.render_drift(hits, checked) + drift.render_governs_nothing(list(missing))
              + drift.render_off_branch(elsewhere))
    if not args.gate:
        return 0
    # Under --gate the exit code is the verdict, and it follows the CLI's contract:
    # 1 = ran and found drift, 2 = did not run. A gate that checked no rule did not run,
    # however clean its output looks.
    if hits:
        return 1
    return 2 if checked == 0 else 0
