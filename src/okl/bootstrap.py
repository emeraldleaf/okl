"""Factory bootstrapping (Codified Context §5.1 — factory agents that generate each tier).

Their companion repo ships agents that generate the initial infrastructure for a new
project. OKL's analogue: instead of stamping only static templates, *read the repo's own
signals* — git history, existing docs, an existing `.claude/` — and propose a starter set
of okl nodes for a human to review and seed.

This is deliberately NOT an autonomous LLM interview at install time (the kit can't assume
network/model access when `okl init` runs). It emits a reviewable `okl-bootstrap.json` in
the same format `okl seed` consumes; the human edits it, then `okl seed okl-bootstrap.json`.
The point is to lower the empty-store cold-start, not to fabricate lessons.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _git(args: list[str], repo_dir: str) -> str:
    """Run a git command in `repo_dir`, returning stdout or '' on any failure.

    Failure is normal here: bootstrap runs in directories that may not be repos at
    all. It returns empty rather than raising so the caller degrades to fewer
    proposals instead of aborting.
    """
    try:
        out = subprocess.run(["git", "-C", repo_dir, *args],
                             capture_output=True, text=True, timeout=20)
        return out.stdout if out.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def propose_nodes(repo: str, repo_dir: str = ".") -> dict[str, Any]:
    """Return a seed-format dict of PROPOSED starter nodes derived from repo signals.

    Every proposed node is marked unverified and tagged in its body as a bootstrap
    proposal, so a human must confirm it (and choose scope) before it becomes canon.
    """
    nodes: list[dict] = []

    # 1) Fix/bug commits → candidate Defect nodes (the repo already told us what broke).
    log = _git(["log", "--no-merges", "-n", "400", "--format=%h%x09%s"], repo_dir)
    fix_kw = ("fix", "bug", "revert", "hotfix", "regression", "broke", "incorrect", "wrong")
    seen = set()
    for line in log.splitlines():
        if "\t" not in line:
            continue
        sha, subj = line.split("\t", 1)
        low = subj.lower()
        if any(k in low for k in fix_kw):
            key = subj.strip().lower()[:60]
            if key in seen:
                continue
            seen.add(key)
            nodes.append({
                "key": f"boot_fix_{sha}",
                "type": "Defect",
                "title": subj.strip()[:120],
                "scope": f"repo:{repo}",
                "body": f"[BOOTSTRAP PROPOSAL from commit {sha}] Review: is this a recurring "
                        f"class worth encoding? If so, write the symptom/cause/fix and set scope.",
                "found_by": "bootstrap: git fix-commit scan",
            })
        if len(nodes) >= 25:
            break

    # 2) Existing docs → candidate Rule/Deep-reference pointers (don't ingest text, point at it).
    docs = []
    for pat in ("docs", "doc"):
        dd = Path(repo_dir) / pat
        if dd.is_dir():
            docs += [p for p in dd.rglob("*.md")]
    for p in docs[:15]:
        rel = p.relative_to(repo_dir)
        nodes.append({
            "key": f"boot_doc_{abs(hash(str(rel))) % 10**8}",
            "type": "Rule",
            "title": f"See {rel}",
            "scope": f"repo:{repo}",
            "body": "[BOOTSTRAP PROPOSAL] Existing doc — extract any durable rule and encode it, "
                    "or leave as a deep-reference pointer.",
            "files": str(rel),
        })

    note = ("PROPOSED nodes from repo signals — NOT yet canon. Review titles/scope, add "
            "symptom/cause/fix, delete noise, then `okl seed okl-bootstrap.json`.")
    return {"_comment": note, "nodes": nodes, "edges": []}
