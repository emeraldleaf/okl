"""Source-vs-spec drift detection.

The problem (Codified Context, arXiv 2602.20478 §5.2 — their *primary* failure mode):
an encoded rule points at code, the code changes, the rule is never revisited, and the
agent is now primed with a stale mental model. OKL already catches two drift classes —
doc-orphans (a doc nobody links) and resurrected tombstones (a retired id reused) — but
nothing catches "the code this rule governs moved after the rule was last verified."

This closes that gap. A node may declare `files` (comma-separated path globs it governs).
`okl verify` records the commit its check passed at, and the node has *drifted* when the
governed files differ between that commit and HEAD (or it was never verified) — its source
changed under it and a human should re-verify it. A verification that recorded no commit,
or one this history does not contain, falls back to comparing the governed files' last
commit time with `verified_at`.

Unlike the passive TTL clock (store.Node.is_stale), this is event-driven: it fires exactly
when the governed code moves, not on a fixed schedule.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import Node


@dataclass
class DriftHit:
    node_id: str
    title: str
    scope: str
    files: str
    last_change_ms: int          # newest governed-file commit, epoch ms
    verified_at: int | None      # node's last verification, epoch ms (None = never)
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "title": self.title, "scope": self.scope,
            "files": self.files, "last_change_ms": self.last_change_ms,
            "verified_at": self.verified_at, "reason": self.reason,
        }



def _utc_day(ms: int) -> str:
    """Epoch-ms -> YYYY-MM-DD in UTC.

    `utcfromtimestamp` is deprecated from 3.12 and returns a naive datetime that silently
    reads as local time wherever it is later compared or formatted. Drift timestamps are
    compared against git commit times across machines and timezones, so naive is wrong.
    """
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).strftime("%Y-%m-%d")

def _git_last_change_ms(globs: list[str], repo_dir: str) -> int | None:
    """Epoch-ms of the most recent commit touching any path matching `globs`.

    Uses `git log -1 --format=%ct -- <pathspec...>`. Returns None if git is
    unavailable, the dir isn't a repo, or no commit ever touched those paths.
    """
    pathspecs = [g.strip() for g in globs if g.strip()]
    if not pathspecs:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "log", "-1", "--format=%ct", "--", *pathspecs],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    ts = out.stdout.strip()
    if not ts:
        return None
    try:
        return int(ts) * 1000  # git %ct is epoch *seconds*
    except ValueError:
        return None


# A commit is passed to `git diff`, so anything but a hex object name is not used: a shared
# store or a committed snapshot can hold whatever someone wrote into it.
_COMMIT = re.compile(r"[0-9a-f]{7,64}")


def _git_changed_since(commit: str | None, globs: list[str], repo_dir: str) -> bool | None:
    """Whether the governed files differ between `commit` and HEAD; None if git can't say.

    Compares content, not history: a change and its revert, or a squash of the commits a
    check already saw, leave the files as verified. None (no commit recorded, or one this
    clone does not have) sends the caller back to comparing times.
    """
    pathspecs = [g.strip() for g in globs if g.strip()]
    if not commit or not _COMMIT.fullmatch(commit) or not pathspecs:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "diff", "--quiet", "--no-ext-diff", "--no-textconv",
             commit, "HEAD", "--", *pathspecs],
            capture_output=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return {0: False, 1: True}.get(out.returncode)   # 128: commit unknown to this clone


def _changed_since_check(commit: str | None, verified_at: int, last_change_ms: int,
                         globs: list[str], repo_dir: str) -> bool:
    """The one drift verdict for a verified rule, shared by the gate and the briefing.

    Comparing times alone missed a commit made in the same second as the verification,
    because git keeps commit time to the second and `verified_at` is in milliseconds
    (#102), and it trusted whatever clock made each commit. The recorded commit has
    neither problem; time is only the fallback for verifications that recorded none.
    """
    since = _git_changed_since(commit, globs, repo_dir)
    return since if since is not None else last_change_ms > verified_at


def detect_drift(nodes: Iterable[Node], repo: str, repo_dir: str = ".") -> list[DriftHit]:
    """Return nodes whose governed source changed after they were last verified.

    See scan_drift for the same result plus the number of rules actually checked, which
    is what a caller needs to tell "no drift" from "nothing was checked".

    `nodes` is any iterable of Node (Client.all_nodes() in local OR remote mode) —
    drift is mode-agnostic on the node side; only the git lookup is local to `repo_dir`.
    In scope: org nodes and this repo's own nodes (the same curation boundary as check()).
    Only nodes with a non-empty `files` glob list participate.
    """
    return scan_drift(nodes, repo, repo_dir)[0]


def scan_drift(nodes: Iterable[Node], repo: str, repo_dir: str = ".") -> tuple[list[DriftHit], int]:
    """Detect drift, and count the rules that were actually checked.

    A rule counts as checked only if it is in scope, declares `files`, and git could
    attribute a change to those files. Anything less is not a verdict either way, and
    an empty result with nothing checked is not "no drift": it is no evidence at all.
    """
    repo_scope = f"repo:{repo}"
    hits: list[DriftHit] = []
    checked = 0
    for n in nodes:
        if not (n.scope == "org" or n.scope == repo_scope):
            continue
        if not n.files:
            continue
        globs = [g for g in n.files.split(",") if g.strip()]
        last = _git_last_change_ms(globs, repo_dir)
        if last is None:
            continue  # git couldn't attribute a change — not evidence of drift
        checked += 1
        base = n.verified_at
        if base is None:
            hits.append(DriftHit(
                n.id, n.title, n.scope, n.files, last, None,
                "governed source has commits but the rule was never verified",
            ))
        elif _changed_since_check(n.verified_commit, base, last, globs, repo_dir):
            hits.append(DriftHit(
                n.id, n.title, n.scope, n.files, last, base,
                "governed source changed after the rule was last verified",
            ))
    return hits, checked


def _governed_paths_exist(globs: list[str], repo_dir: str) -> bool:
    """Whether any governed path exists in this checkout, committed or not."""
    root = Path(repo_dir)
    for g in (g.strip().rstrip("/") for g in globs):
        if not g:
            continue
        try:
            if any(c in g for c in "*?["):
                if next(root.glob(g), None) is not None:
                    return True
            elif (root / g).exists():
                return True
        except (ValueError, NotImplementedError):   # an absolute or malformed pattern
            continue
    return False


def _record_drift(rec: dict[str, Any], repo_scope: str, repo_dir: str) -> dict[str, Any] | None:
    """scan_drift's verdict for one briefed record (a dict, as check returns it), or None."""
    if not rec.get("files") or rec.get("scope") not in ("org", repo_scope):
        return None
    globs = [g for g in rec["files"].split(",") if g.strip()]
    last = _git_last_change_ms(globs, repo_dir)
    base = rec.get("verified_at")
    if base is None:
        # Never verified. Say so whenever the governed code is here, committed or not: a
        # lesson about a new, uncommitted file has no git time yet and was left unmarked
        # (CodeRabbit on #101). A lesson whose files are not in this repo stays quiet.
        if last is None and not _governed_paths_exist(globs, repo_dir):
            return None
        out = {"files": rec["files"], "reason": "never verified"}
        if last is not None:
            out["changed"] = _utc_day(last)
        return out
    # Same verdict as scan_drift, from the same function, so the briefing and the CI gate
    # never disagree.
    if last is None or not _changed_since_check(rec.get("verified_commit"), base, last,
                                                globs, repo_dir):
        return None
    return {"files": rec["files"], "changed": _utc_day(last), "verified": _utc_day(base),
            "reason": "changed since last verified"}


def annotate_briefing(result: dict[str, Any], repo: str, repo_dir: str = ".") -> int:
    """Mark the briefed lessons whose governed code changed after their last check (#93).

    Until now only `okl drift` and the CI gate said so; the briefing that puts a lesson in
    front of the agent stayed silent, so the agent trusted a lesson that might no longer
    hold. Copilot Memory re-checks citations before using a fact for the same reason.
    Only the briefed records are checked (one `git log` each), and it runs on the client
    because a shared service has no checkout of this repo. Returns how many were marked.
    """
    repo_scope = f"repo:{repo}"
    verdicts: dict[str, dict[str, Any] | None] = {}
    for key, value in result.items():
        if key == "next_actions" or not isinstance(value, list):
            continue
        for rec in value:
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            if rec["id"] not in verdicts:
                verdicts[rec["id"]] = _record_drift(rec, repo_scope, repo_dir)
            if verdicts[rec["id"]]:
                rec["drift"] = verdicts[rec["id"]]
    # A routed action is the same record, shown once at the top; it carries the mark too.
    for action in result.get("next_actions") or []:
        if verdicts.get(action.get("id")):
            action["drift"] = verdicts[action["id"]]
    marked = sum(1 for v in verdicts.values() if v)
    if marked:
        result["drifted"] = marked
    return marked


def _head_files(repo_dir: str) -> list[str] | None:
    """Every path committed at HEAD, or None when git cannot say (no repo, no commits)."""
    try:
        out = subprocess.run(["git", "-C", repo_dir, "ls-tree", "-r", "--name-only", "-z", "HEAD"],
                             capture_output=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def _glob_matches(glob: str, path: str) -> bool:
    """git's default pathspec: the path itself, a directory above it, or an fnmatch
    pattern whose `*` also crosses `/` -- the same matching drift's `git log` applies."""
    g = glob.strip().rstrip("/")
    return bool(g) and (path == g or path.startswith(g + "/") or fnmatch.fnmatchcase(path, g))


def governs_nothing(nodes: Iterable[Node], repo: str, repo_dir: str = ".") -> list[Node]:
    """This repo's lessons whose `files` match nothing committed at HEAD (#109).

    Drift is silent about them: the deletion is the last change git reports, and a lesson
    stamped after it, or diffed against a commit that also lacked the file, reads as
    unchanged. It watches nothing, and nothing said so. Only lessons this repo owns are
    judged, scoped to it or recorded in it: an org lesson's files may live in another repo.
    A finding, not drift: re-pointing, dropping `files` or retiring it is a decision.
    """
    paths = _head_files(repo_dir)
    if paths is None:
        return []
    repo_scope = f"repo:{repo}"
    out = []
    for n in nodes:
        if not n.files or not (n.scope == repo_scope or n.repo == repo):
            continue
        globs = [g for g in n.files.split(",") if g.strip()]
        if not any(_glob_matches(g, p) for g in globs for p in paths):
            out.append(n)
    return out


def render_governs_nothing(nodes: list[Node]) -> str:
    """The advisory under the drift report; empty when every lesson's files exist."""
    if not nodes:
        return ""
    lines = ["", f"OKL: {len(nodes)} lesson(s) govern files that match nothing committed here. "
                 "Re-point each at the code it is about, drop its files, or retire it:"]
    lines.extend(f"  • [{n.id}] {n.title}  (files: {n.files})" for n in nodes)
    return "\n".join(lines)


def render_drift(hits: list[DriftHit], checked: int | None = None) -> str:
    """Format drift hits for a terminal, or the all-clear line.

    The all-clear is deliberately explicit rather than silent: "no output" and "the
    check did not run" look identical, and only one of them is safe.
    """
    # This docstring's own point was once violated right here: with nothing checked, the
    # all-clear still printed, so an empty store reported "OK" in CI (issue #21). The
    # all-clear now states how many rules it rests on, and says so when that is zero.
    if not hits and checked == 0:
        return ("OKL drift: NOTHING CHECKED — no rule governing files in this repo was found, "
                "so this is not an all-clear.")
    if not hits:
        basis = f"{checked} rule(s) checked, " if checked is not None else ""
        return (f"OKL drift: OK — {basis}no encoded rule's governed source changed after its "
                "last verification.")
    lines = [f"OKL drift: {len(hits)} rule(s) may be stale (source changed after verification):", ""]
    for h in hits:
        when = _utc_day(h.last_change_ms)
        ver = ("never verified" if h.verified_at is None
               else "verified " + _utc_day(h.verified_at))
        lines.append(f"  • [{h.node_id}] {h.title}")
        lines.append(f"      files: {h.files}")
        lines.append(f"      last source change: {when} · {ver} → {h.reason}")
    # Once, in plain words. Each hit used to carry `okl verify <id> --run "<a check that fails
    # if the rule is broken>" --expect "<its success signal>"`, which named three things a
    # person had no way to fill in. (Before that it recommended `okl record --verified`, i.e.
    # clearing drift by assertion -- the one thing verify exists to prevent.)
    lines += ["",
              "To re-check them: `okl reverify` re-runs each lesson's stored check. A lesson with no",
              "stored check needs one first: ask your agent to \"re-check the stale okl lessons\", or run",
              "`okl verify <id>` to see the lesson and the tests that touch its files. If a check fails,",
              "fix the code, or change the lesson on purpose."]
    return "\n".join(lines)


# -- committed snapshot (issue #36) ---------------------------------------------------
#
# CI usually has no store: the local one is gitignored and a hosted service is optional,
# and fork PRs get no secrets either way. So drift ran, checked nothing, and warned. The
# obvious fix -- commit the rules and `okl seed` them in CI -- is a false all-clear:
# seeding goes through record(), which stamps verified_at fresh, so nothing ever drifts.
# A snapshot is read straight into Node objects instead, with its real timestamps.

SNAPSHOT_FILE = "okl-drift.json"
SNAPSHOT_FORMAT = "okl-drift-snapshot/1"
_FIELDS = ("id", "type", "title", "scope", "files", "verified_at", "verified_by", "verified_commit")
# The commit sits BEFORE the time stamp, so an okl older than #102 still finds the stamp
# at the end and keeps reading the snapshot (it just compares times).
_STAMP = re.compile(r"(?: on commit ([0-9a-f]{7,64}))? @ (\d{4}-\d\d-\d\dT\d\d:\d\dZ)$")
# `okl verify` writes its evidence stamp (minute resolution) just before the store sets
# verified_at, so the two can straddle a minute boundary, and a remote service's clock is
# not the caller's. So verified_at must fall from one minute before the stamped minute to
# five minutes after it -- a hand edit can move it that far at most, never past a commit
# made later than that. Pinned at both edges by a test.
_STAMP_SKEW_MS = (-60_000, 5 * 60_000)


def snapshot(nodes: Iterable[Node], repo: str) -> dict[str, Any]:
    """The rules drift would check for `repo`, in the committed-file shape.

    Only what drift reads: no bodies, so the file publishes titles and evidence, not
    lessons. Sorted and with no generated timestamp, so an unchanged store exports
    byte-identically and the diff shows exactly which verifications moved.
    """
    repo_scope = f"repo:{repo}"
    rules = [{f: getattr(n, f) for f in _FIELDS} for n in nodes
             if n.files and (n.scope == "org" or n.scope == repo_scope)]
    return {"format": SNAPSHOT_FORMAT, "repo": repo,
            "rules": sorted(rules, key=lambda r: r["id"])}


def dump_snapshot(snap: dict[str, Any]) -> str:
    return json.dumps(snap, indent=2, ensure_ascii=False) + "\n"


def stamp_problem(rule: dict[str, Any]) -> str | None:
    """Why this entry's verification cannot be trusted, or None.

    The snapshot is an ordinary file, so its verified_at can be edited. An entry is
    accepted only when verified_at falls at the minute `okl verify` stamped into its
    evidence: editing the number alone is refused. Editing both is still possible -- it
    is a deliberate forgery in a reviewed diff, and review is the guard for that.
    """
    at = rule.get("verified_at")
    if at is None:
        return None                      # never verified: drift reports it, nothing to trust
    m = _STAMP.search(rule.get("verified_by") or "")
    if not m:
        return "verified_at is set but verified_by carries no `okl verify` evidence stamp"
    stamped = int(_dt.datetime.strptime(m.group(2), "%Y-%m-%dT%H:%MZ")
                  .replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)
    lo, hi = _STAMP_SKEW_MS
    if not (stamped + lo <= at < stamped + hi):
        return (f"verified_at ({_utc_day(at)}) does not match the evidence stamp "
                f"({m.group(2)}) -- edited by hand?")
    # The commit is bound the same way. Unbound, setting it to HEAD would clear drift with
    # one edit -- the forgery the stamp check exists to stop.
    commit = rule.get("verified_commit")
    if commit is not None and not (m.group(1) and commit.startswith(m.group(1))):
        return "verified_commit does not match the commit its evidence names -- edited by hand?"
    return None


def read_committed_snapshot(path: str, repo_dir: str = ".") -> dict[str, Any]:
    """The snapshot as COMMITTED at HEAD, never the working-tree copy.

    An audit reads the repo, not the dirty tree (CLAUDE.md): an uncommitted edit must not
    pass a gate that main would fail. Raises ValueError, with the reason, when the file is
    untracked or not a snapshot.
    """
    top = subprocess.run(["git", "-C", repo_dir, "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        raise ValueError(f"{repo_dir!r} is not a git repository")
    rel = subprocess.run(["git", "-C", repo_dir, "ls-files", "--full-name", "--", path],
                         capture_output=True, text=True).stdout.strip()
    if not rel:
        raise ValueError(f"{path} is not committed -- a gate reads committed files only")
    out = subprocess.run(["git", "-C", repo_dir, "show", f"HEAD:{rel}"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise ValueError(f"{path} is staged but not in HEAD -- commit it first")
    try:
        snap = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(snap, dict) or snap.get("format") != SNAPSHOT_FORMAT:
        raise ValueError(f"{path} is not an {SNAPSHOT_FORMAT} file")
    return snap


def nodes_from_snapshot(snap: dict[str, Any]) -> tuple[list[Node], list[str]]:
    """Nodes to feed scan_drift, and one problem line per entry that cannot be trusted."""
    nodes: list[Node] = []
    problems: list[str] = []
    rules = snap.get("rules")
    if not isinstance(rules, list):
        return [], ["`rules` is not a list"]
    for r in rules:
        # Shape first. The file is hand-editable, and a traceback exits 1 -- which under
        # --gate reads as "drift found" rather than "did not run".
        if not (isinstance(r, dict)
                and all(isinstance(r.get(k), str) for k in ("id", "title", "scope", "files"))
                and (r.get("verified_at") is None or type(r.get("verified_at")) is int)
                and (r.get("verified_by") is None or isinstance(r.get("verified_by"), str))
                and (r.get("verified_commit") is None or isinstance(r.get("verified_commit"), str))):
            rid = r.get("id") if isinstance(r, dict) else None
            problems.append(f"[{rid or '?'}] malformed entry: needs string id/title/scope/"
                            "files and an integer verified_at or null")
            continue
        why = stamp_problem(r)
        if why:
            problems.append(f"[{r.get('id')}] {why}")
            continue
        nodes.append(Node(type=r.get("type") or "Rule", title=r["title"], scope=r["scope"],
                          files=r["files"], verified_at=r.get("verified_at"),
                          verified_by=r.get("verified_by"),
                          verified_commit=r.get("verified_commit"), id=r["id"]))
    return nodes, problems
