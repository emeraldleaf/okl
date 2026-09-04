#!/usr/bin/env python3
"""Render docs/okl-retrieval-pipeline.svg from the LIVE pipeline, not from memory.

Why generated rather than drawn: a hand-authored diagram of `check()` carries counts that
someone transcribed once. Two things then happen. It goes stale silently — the first draft
of this diagram said 207 records and was wrong within ten minutes, because recording three
lessons while writing it moved the number. And transcription is a place to be wrong: that
draft also had the stage-3 and stage-4 counts backwards (0/9 rather than 3/6), written from
memory of an earlier measurement that had asked a different question.

So the numbers here are TRACED, by calling the same `store.search` and `core._in_scope` that
serve real briefings. If the pipeline changes, this diagram changes with it or the freshness
test fails (tests/test_okl.py::test_pipeline_diagram_is_current). That is the difference
between a render that exists and a render that is true — the gap gates/check-diagram-pairs.sh
documents as "stays human".

Usage:
  python3 docs/render_pipeline_diagram.py            # write the SVG
  python3 docs/render_pipeline_diagram.py --json     # emit traced counts only
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from okl.core import _in_scope  # noqa: E402
from okl.store import Store, split_tags  # noqa: E402

# The task traced through the pipeline. A real eval task, so the diagram depicts a case the
# report also measures rather than a contrived one.
TRACE_TASK = "Add an endpoint that returns a single order by id for the signed-in user."
TRACE_REPO = "okl"
LIMIT = 12


# Traced against a store built from seed/, NOT the developer's .okl/okl.db. The local store
# is gitignored and grows every time anyone records a lesson, so a diagram traced from it
# depicts one machine at one moment and can never be reproduced in CI — the freshness test
# would fail on a clean checkout and pass nowhere twice. Seeding from committed files makes
# the counts a property of the repository, which is the only thing a reviewer can check.
SEED_INTERESTS = ["python", "method", "security", "agent-safety",
                  "retrieval-design", "eval-integrity", "data-quality"]


def _seeded_store(tmpdir: str) -> Store:
    """Build a store from every committed seed file, via the shipped seed path."""
    url = f"sqlite:///{Path(tmpdir) / 'trace.db'}"
    env = {**os.environ, "OKL_DATABASE_URL": url}
    for f in sorted((REPO / "seed").glob("*.json")):
        r = subprocess.run([sys.executable, "-m", "okl", "seed", str(f)],
                           capture_output=True, text=True, env=env, cwd=REPO)
        if r.returncode != 0:
            raise SystemExit(f"ABORT: seeding {f.name} failed — {r.stderr.strip()[:200]}")
    store = Store(url)
    # verify_materialized: assert records actually landed, never trust exit 0. The first
    # version of this function printed "seeded 10 records" while writing nothing here,
    # because the CLI ignored OKL_DATABASE_URL and wrote to the developer's own store —
    # a green run and an empty output, which is the armed gate's exact case.
    if not store.all_nodes():
        raise SystemExit("ABORT: seeding reported success and the store is empty.")
    return store


def trace(store: Store | None = None) -> dict:
    """Run the real pipeline against the seeded corpus, recording each stage's survivors."""
    tmp = None
    if store is None:
        tmp = tempfile.TemporaryDirectory()
        store = _seeded_store(tmp.name)
    interests = list(SEED_INTERESTS)
    wanted = set(interests)
    repo_scope = f"repo:{TRACE_REPO}"

    total = len(store.all_nodes())
    fetched = store.search(TRACE_TASK, limit=LIMIT * 3)

    own = [n for n in fetched if n.scope == repo_scope]
    org = [n for n in fetched if n.scope == "org"]
    after_scope = own + org

    # Stage 3 — applies_to, the only EXCLUSIVE filter. Own-repo records never reach it.
    def gated(n):
        a = split_tags(n.applies_to) - {"any"}
        return bool(a and wanted and not (a & wanted))

    dropped_applies = [n for n in org if gated(n)]
    after_applies = own + [n for n in org if not gated(n)]

    # Stage 4 — tags, INCLUSIVE: untagged always passes, one shared subject is enough.
    def off_subject(n):
        t = split_tags(n.tags)
        return bool(t and wanted and not (t & wanted))

    dropped_tags = [n for n in after_applies if n.scope == "org" and off_subject(n)]
    after_tags = [n for n in after_applies if n not in dropped_tags]

    # Cross-check the hand-rolled trace against the real predicate. If these ever disagree,
    # the diagram is depicting a pipeline the code does not run — the exact failure mode
    # this file exists to prevent, so it aborts rather than rendering a plausible fiction.
    truth = [n for n in fetched if _in_scope(n, repo_scope, interests)]
    if {n.id for n in truth} != {n.id for n in after_tags}:
        raise SystemExit("ABORT: traced stages disagree with core._in_scope — fix the trace "
                         "before rendering, or the diagram depicts a pipeline nobody runs.")

    applies_set = sum(1 for n in store.all_nodes()
                      if (n.applies_to or "").strip() and n.applies_to.strip().lower() != "any")
    out = {
        "task": TRACE_TASK, "repo": TRACE_REPO, "limit": LIMIT,
        "interests": interests,
        "corpus": total,
        "applies_to_set": applies_set,
        "fetched": len(fetched),
        "after_scope": len(after_scope), "dropped_scope": len(fetched) - len(after_scope),
        "after_applies": len(after_applies), "dropped_applies": len(dropped_applies),
        "after_tags": len(after_tags), "dropped_tags": len(dropped_tags),
        "delivered": min(LIMIT, len(after_tags)),
        "trimmed": max(0, len(after_tags) - LIMIT),
    }
    if tmp is not None:
        store.close(); tmp.cleanup()
    return out


# --- SVG ---------------------------------------------------------------------
# Plain geometry and a system font stack: forges sanitise SVG, so no external font can load
# and no script will run. An explicit light ground keeps it legible in either forge theme.
W, ROW_H, PAD = 980, 96, 28
FONT = "ui-sans-serif,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
INK, INK2, INK3 = "#1E1B18", "#4E4740", "#7C736A"
FLOW, PASS, DROP = "#B4531F", "#4A6B3D", "#9B3B3B"
PAPER, SURF, RULE = "#F5F3F0", "#FFFFFF", "#DCD6CE"


def _bar(x, y, w, keep_frac, cut_frac):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="9" rx="2" fill="#EBE7E1"/>']
    kw = round(w * keep_frac)
    out.append(f'<rect x="{x}" y="{y}" width="{kw}" height="9" rx="2" fill="{FLOW}"/>')
    if cut_frac > 0:
        out.append(f'<rect x="{x + kw}" y="{y}" width="{round(w * cut_frac)}" height="9" '
                   f'rx="2" fill="{DROP}" opacity="0.4"/>')
    return "".join(out)


def render(d: dict) -> str:
    f = d["fetched"] or 1
    stages = [
        ("0", "STORE", "The corpus", "Every record carries scope (permission), tags (subject), "
         "applies_to (validity) and files (what it governs). Nothing is ranked yet.",
         f'{d["corpus"]} records', "", 1.0, 0.0, ""),
        ("1", "RANK", "Fetch 3x more candidates than needed",
         "SQLite FTS5, weighted title x8, body x4, symptom x4, fix x2. Tags are NOT indexed - "
         "a tag can get a record excluded, never help it be found.",
         f'{d["fetched"]} fetched', "limit x 3", d["fetched"] / f, 0.0, ""),
        ("2", "SCOPE", "Permission - who may see this",
         "A repo's own records pass first and unconditionally. org records continue. Another "
         "repo's records stop here: the curation boundary.",
         f'{d["after_scope"]} survive', f'{d["dropped_scope"]} dropped: other repos',
         d["after_scope"] / f, d["dropped_scope"] / f, "DROPS"),
        ("3", "VALID", "applies_to - the only filter allowed to exclude",
         f'EXCLUSIVE. Set by hand on {d["applies_to_set"]} of {d["corpus"]} records, only where a '
         "lesson is false off-stack. Unset means anywhere, which is why it is safe.",
         f'{d["after_applies"]} survive', f'{d["dropped_applies"]} dropped: off-stack',
         d["after_applies"] / f, d["dropped_applies"] / f, "DROPS"),
        ("4", "SUBJECT", "tags x interests - one shared subject is enough",
         "INCLUSIVE. Untagged always passes. The exclusive version was built, reviewed and "
         "REVERTED: it hid 35 of 172 records and the briefed arm reproduced a defect whose "
         "rule it had dropped (REPORT 4d).",
         f'{d["after_tags"]} survive', f'{d["dropped_tags"]} dropped: no shared subject',
         d["after_tags"] / f, d["dropped_tags"] / f, "ANY-MATCH"),
        ("5", "CUTOFF", "Top 12, and the rest are counted not hidden",
         "Full-text matching is permissive enough that a plausible task matches most of a "
         "mature store. The number discarded travels with the result.",
         f'{d["delivered"]} delivered', f'{d["trimmed"]} reported as trimmed',
         d["delivered"] / f, d["trimmed"] / f, "TRUNCATES"),
        ("6", "SHAPE", "Bucket by type, then route to imperatives",
         "Eight buckets: gates, defects, retractions, tombstones, threat prior-art, rules, "
         "vocabulary, stale warnings. Stale demotes, never deletes. Then ARM / FIX / AVOID.",
         "gates -> defects+rules", "-> retractions -> tombstones", 0.0, 0.0, ""),
        ("7", "RENDER", "Three surfaces, one pipeline",
         "agent | actions | json. A zero-match result carries the store size, so 'no rules "
         "apply' can never be confused with 'the store is empty'.",
         "hook | MCP | CI", "", 0.0, 0.0, ""),
    ]
    h = 166 + len(stages) * ROW_H + 60
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
         f'viewBox="0 0 {W} {h}" font-family="{FONT}">',
         f'<rect width="{W}" height="{h}" fill="{PAPER}"/>']
    o.append(f'<text x="{PAD}" y="46" font-size="27" font-weight="700" fill="{INK}">'
             f'How an okl briefing gets built</text>')
    o.append(f'<text x="{PAD}" y="72" font-size="14" fill="{INK2}">'
             f'{escape(str(d["corpus"]))} records and one task sentence become the '
             f'{d["limit"]} an agent reads. Two stages can drop a record; only one is entitled to.'
             f'</text>')
    for i, ln in enumerate([
        "GENERATED from the live pipeline - docs/render_pipeline_diagram.py",
        f'traced task: "{d["task"]}"',
        f'repo interests: {", ".join(d["interests"])}',
    ]):
        o.append(f'<text x="{PAD}" y="{96 + i * 16}" font-size="11.5" font-family="{MONO}" '
                 f'fill="{INK3}">{escape(ln)}</text>')
    y = 154
    for n, lbl, title, body, c1, c2, keep, cut, verdict in stages:
        o.append(f'<rect x="{PAD}" y="{y}" width="{W - 2 * PAD}" height="{ROW_H - 6}" '
                 f'fill="{SURF}" stroke="{RULE}"/>')
        o.append(f'<rect x="{PAD}" y="{y}" width="74" height="{ROW_H - 6}" fill="#EBE7E1" '
                 f'stroke="{RULE}"/>')
        o.append(f'<text x="{PAD + 37}" y="{y + 38}" font-size="26" font-weight="700" '
                 f'fill="{FLOW}" font-family="{MONO}" text-anchor="middle">{n}</text>')
        o.append(f'<text x="{PAD + 37}" y="{y + 56}" font-size="9" fill="{INK3}" '
                 f'font-family="{MONO}" text-anchor="middle" letter-spacing="1">{lbl}</text>')
        tx = PAD + 92
        o.append(f'<text x="{tx}" y="{y + 25}" font-size="15" font-weight="600" fill="{INK}">'
                 f'{escape(title)}</text>')
        # wrap the body at ~92 chars
        words, line, lines = body.split(), "", []
        for w_ in words:
            if len(line) + len(w_) + 1 > 92:
                lines.append(line); line = w_
            else:
                line = f"{line} {w_}".strip()
        lines.append(line)
        for i, ln in enumerate(lines[:2]):
            o.append(f'<text x="{tx}" y="{y + 44 + i * 15}" font-size="12" fill="{INK2}">'
                     f'{escape(ln)}</text>')
        if verdict:
            col = DROP if verdict in ("DROPS", "TRUNCATES") else PASS
            o.append(f'<text x="{W - PAD - 14}" y="{y + 25}" font-size="9.5" fill="{col}" '
                     f'font-family="{MONO}" font-weight="700" text-anchor="end" '
                     f'letter-spacing="0.8">{verdict}</text>')
        o.append(f'<text x="{tx}" y="{y + ROW_H - 26}" font-size="11.5" font-family="{MONO}" '
                 f'fill="{INK}" font-weight="500">{escape(c1)}</text>')
        if c2:
            o.append(f'<text x="{W - PAD - 14}" y="{y + ROW_H - 26}" font-size="11.5" '
                     f'font-family="{MONO}" fill="{INK3}" text-anchor="end">{escape(c2)}</text>')
        if keep > 0:
            o.append(_bar(tx, y + ROW_H - 20, W - PAD - tx - 14, keep, cut))
        y += ROW_H
    o.append(f'<text x="{PAD}" y="{h - 26}" font-size="11" font-family="{MONO}" fill="{INK3}">'
             f'src/okl/core.py check() / _in_scope() . src/okl/store.py search() . '
             f'regenerate: python3 docs/render_pipeline_diagram.py</text>')
    o.append("</svg>")
    return "\n".join(o) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit traced counts, render nothing")
    ap.add_argument("--out", default=str(REPO / "docs" / "okl-retrieval-pipeline.svg"))
    a = ap.parse_args()
    d = trace()
    if a.json:
        print(json.dumps(d, indent=2))
        return 0
    Path(a.out).write_text(render(d))
    # --out may point outside the repo (the freshness test regenerates to a scratch dir),
    # so relative_to is a best effort, not a guarantee.
    try:
        shown = Path(a.out).relative_to(REPO)
    except ValueError:
        shown = Path(a.out)
    print(f"wrote {shown}  "
          f"({d['corpus']} records -> {d['fetched']} -> {d['after_scope']} -> "
          f"{d['after_applies']} -> {d['after_tags']} -> {d['delivered']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
