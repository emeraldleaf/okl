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
        lines.append("      fix: re-verify against current source, then `okl record --verified` to reset, "
                     "or update the rule.")
    return "\n".join(lines)
