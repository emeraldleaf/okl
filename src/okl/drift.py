"""Source-vs-spec drift detection.

The problem (Codified Context, arXiv 2602.20478 §5.2 — their *primary* failure mode):
an encoded rule points at code, the code changes, the rule is never revisited, and the
agent is now primed with a stale mental model. OKL already catches two drift classes —
doc-orphans (a doc nobody links) and resurrected tombstones (a retired id reused) — but
nothing catches "the code this rule governs moved after the rule was last verified."

This closes that gap. A node may declare `files` (comma-separated path globs it governs).
For each such node we ask git for the last commit that touched any matching path; if that
commit is newer than the node's `verified_at` (or the node was never verified), the node
has *drifted* — its source changed under it and a human should re-verify it.

Unlike the passive TTL clock (store.Node.is_stale), this is event-driven: it fires exactly
when the governed code moves, not on a fixed schedule.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
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
        elif last > base:
            hits.append(DriftHit(
                n.id, n.title, n.scope, n.files, last, base,
                "governed source changed after the rule was last verified",
            ))
    return hits, checked


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
        # This line used to recommend `okl record --verified`, i.e. clearing drift by
        # assertion -- the one thing the verify command exists to prevent.
        lines.append(f"      fix: okl verify {h.node_id} --run \"<a check that fails if the rule "
                     "is broken>\" --expect \"<its success signal>\" — or update the rule.")
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
_FIELDS = ("id", "type", "title", "scope", "files", "verified_at", "verified_by")
_STAMP = re.compile(r"@ (\d{4}-\d\d-\d\dT\d\d:\d\dZ)$")
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
    stamped = int(_dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%MZ")
                  .replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)
    lo, hi = _STAMP_SKEW_MS
    if not (stamped + lo <= at < stamped + hi):
        return (f"verified_at ({_utc_day(at)}) does not match the evidence stamp "
                f"({m.group(1)}) -- edited by hand?")
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
                and (r.get("verified_by") is None or isinstance(r.get("verified_by"), str))):
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
                          verified_by=r.get("verified_by"), id=r["id"]))
    return nodes, problems
