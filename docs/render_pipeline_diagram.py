#!/usr/bin/env python3
"""Render docs/okl-retrieval-pipeline.svg from the LIVE pipeline, not from memory.

Why generated rather than drawn: a hand-authored diagram of `check()` carries counts that
someone transcribed once. Two things then happen. It goes stale silently — the first draft
of this diagram said 207 records and was wrong within ten minutes, because recording three
lessons while writing it moved the number. And transcription is a place to be wrong: that
draft also had the stage-3 and stage-4 counts backwards (0/9 rather than 3/6), written from
memory of an earlier measurement that had asked a different question.

So the numbers here are TRACED, by calling the same `briefing_terms`, `store.search`,
`core._in_scope` and `core._live_hits` that serve real briefings. The first version searched
the raw task sentence; `okl check` has searched only its subject words since 0.8.6, so for a
release the diagram showed a query nobody ran, and its freshness test, which compares this
script's output with the committed render, could not notice. The trace now cross-checks its
result against `_live_hits` itself. If the pipeline changes, this diagram changes with it or the freshness
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

from okl import semantic  # noqa: E402
from okl.core import (  # noqa: E402
    _apply_floor,
    _in_scope,
    _live_hits,
    briefing_terms,
    check,
    ranked_candidates,
)
from okl.store import Node, Store, split_tags  # noqa: E402

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
    # The seeds must land in this throwaway store and nowhere else. A service URL in the
    # environment, or in the checkout's own .okl/config.json, would put the client in remote
    # mode and send them to the live service (reviews on #266 and #267), so the subprocess
    # runs from the temporary directory, outside any config's ancestor tree, with the
    # variable dropped, the database named, and the checkout's source on its import path.
    env = {k: v for k, v in os.environ.items() if k != "OKL_SERVICE_URL"}
    env["OKL_DATABASE_URL"] = url
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO / "src"), env.get("PYTHONPATH", "")) if p)
    for f in sorted((REPO / "seed").glob("*.json")):
        r = subprocess.run([sys.executable, "-m", "okl", "seed", str(f)],
                           capture_output=True, text=True, env=env, cwd=tmpdir)
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


def trace(store: Store | None = None, hybrid: str | None = None) -> dict:
    """Run the real pipeline against the seeded corpus, recording each stage's survivors.

    With `hybrid`, the seeded corpus is embedded from the locally cached model first and the
    candidates come from the fused order check() uses; the trace aborts if the semantic arm
    cannot run here, rather than drawing a full-text pipeline under a hybrid title.
    """
    tmp = None
    if store is None:
        tmp = tempfile.TemporaryDirectory()
        store = _seeded_store(tmp.name)
    interests = list(SEED_INTERESTS)
    wanted = set(interests)
    repo_scope = f"repo:{TRACE_REPO}"

    total = len(store.all_nodes())
    # Stage 1: the search runs on the task's subject words, as check() does (core._live_hits),
    # through the same candidate function, so a fused order is traced the way it is served.
    terms = briefing_terms(TRACE_TASK)
    query = " ".join(terms)
    if hybrid:
        semantic.build_index(store, offline=True)
    cand = ranked_candidates(store, TRACE_TASK, LIMIT * 3, hybrid)
    if hybrid and cand.note:
        raise SystemExit(f"ABORT: the semantic arm did not run: {cand.note}")
    fetched = cand.nodes

    own = [n for n in fetched if n.scope == repo_scope]
    org = [n for n in fetched if n.scope == "org"]
    after_scope = own + org

    # Stage 3 — applies_to, the only EXCLUSIVE filter. Own-repo records never reach it.
    def gated(n: Node) -> bool:
        a = split_tags(n.applies_to) - {"any"}
        return bool(a and wanted and not (a & wanted))

    dropped_applies = [n for n in org if gated(n)]
    after_applies = own + [n for n in org if not gated(n)]

    # Stage 4 — tags, INCLUSIVE: untagged always passes, one shared subject is enough.
    def off_subject(n: Node) -> bool:
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

    # Retired lessons (obsolete, or superseded by a live one this repo can see) leave before
    # the cut. Take the survivors from _live_hits itself, the function check() calls; if it had
    # to widen its window, this trace's single fetch no longer matches it, so stop.
    live, _, _, _ = _live_hits(store, TRACE_TASK, LIMIT, repo_scope, interests, hybrid=hybrid)
    live_ids = {n.id for n in live}
    if not live_ids <= {n.id for n in after_tags}:
        raise SystemExit("ABORT: _live_hits widened its search past this trace's window — "
                         "trace the wider fetch before rendering.")
    retired = [n for n in after_tags if n.id not in live_ids]

    # The floor: two shared subject words, or one when the task has only one; a hit below
    # it stays only through a one-step link to a hit above it (core._apply_floor).
    kept, _matched, weak = _apply_floor(store, live, terms, cand)
    # check() widens the fetch when a full window leaves fewer than the limit above the
    # floor. This trace applies the floor to one window, so it asks check() itself and stops
    # if the briefing it would deliver differs from the counts traced here.
    delivered_by_check = check(store, TRACE_REPO, TRACE_TASK, LIMIT, interests, hybrid=hybrid)
    if (delivered_by_check["match_count"] != min(LIMIT, len(kept))
            or delivered_by_check["weak_matches"] != weak):
        raise SystemExit("ABORT: check() widened past this trace's window (its briefing holds "
                         f"{delivered_by_check['match_count']} records, the trace {min(LIMIT, len(kept))}); "
                         "trace the wider fetch before rendering.")

    applies_set = sum(1 for n in store.all_nodes()
                      if (n.applies_to or "").strip() and n.applies_to.strip().lower() != "any")
    out = {
        "task": TRACE_TASK, "query": query, "terms": len(terms), "repo": TRACE_REPO, "limit": LIMIT,
        "interests": interests,
        "corpus": total,
        "applies_to_set": applies_set,
        "fetched": len(fetched),
        "after_scope": len(after_scope), "dropped_scope": len(fetched) - len(after_scope),
        "after_applies": len(after_applies), "dropped_applies": len(dropped_applies),
        "after_tags": len(after_tags), "dropped_tags": len(dropped_tags),
        "retired": len(retired), "live": len(live),
        "after_floor": len(kept), "weak": weak,
        "delivered": min(LIMIT, len(kept)),
        "trimmed": max(0, len(kept) - LIMIT),
        "hybrid": hybrid,
    }
    if hybrid:
        vectors = store.embeddings(semantic.MODEL_ID)
        out.update({
            "lexical": len(cand.lexical), "nearest": len(cand.scores),
            "semantic_only": sum(1 for n in fetched if n.id not in cand.lexical),
            "by_meaning": sum(1 for n in kept if n.id not in cand.lexical),
            "line": semantic.SUBJECT_SIMILARITY,
            "dim": len(semantic.unpack(vectors[0][2])) if vectors else 0,
        })
    if tmp is not None:
        store.close(); tmp.cleanup()
    return out


# --- SVG ---------------------------------------------------------------------
# Plain geometry and a system font stack: forges sanitise SVG, so no external font can load
# and no script will run. An explicit light ground keeps it legible in either forge theme.
W, ROW_H, PAD = 980, 96, 28
MAX_BODY_LINES = 2   # what fits above the count line at this ROW_H
FONT = "ui-sans-serif,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
INK, INK2, INK3 = "#1E1B18", "#4E4740", "#7C736A"
FLOW, PASS, DROP = "#B4531F", "#4A6B3D", "#9B3B3B"
PAPER, SURF, RULE = "#F5F3F0", "#FFFFFF", "#DCD6CE"


def _bar(x: int, y: int, w: int, keep_frac: float, cut_frac: float) -> str:
    """Draw one stage's bar: a track `w` wide, the kept share, then the dropped share.

    `keep_frac` and `cut_frac` are fractions of `w`; the SVG markup comes back as a string.
    """
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="9" rx="2" fill="#EBE7E1"/>']
    kw = round(w * keep_frac)
    out.append(f'<rect x="{x}" y="{y}" width="{kw}" height="9" rx="2" fill="{FLOW}"/>')
    if cut_frac > 0:
        out.append(f'<rect x="{x + kw}" y="{y}" width="{round(w * cut_frac)}" height="9" '
                   f'rx="2" fill="{DROP}" opacity="0.4"/>')
    return "".join(out)


def render(d: dict) -> str:
    """Turn the counts from `trace()` into the complete SVG document text."""
    f = d["fetched"] or 1
    stages = [
        ("0", "STORE", "The corpus", "Every record carries scope (permission), tags (subject), "
         "applies_to (validity) and files (what it governs). Nothing is ranked yet.",
         f'{d["corpus"]} records', "", 1.0, 0.0, ""),
        ("1", "QUERY", "The task's subject words, not the sentence",
         "Function words, chat filler and single characters drop out; each word counts once, "
         "up to 40. A prompt with no subject word is briefed nothing.",
         f'{d["terms"]} words', "searched", 0.0, 0.0, ""),
        ("2", "RANK", "Fetch 3x more candidates than needed",
         "SQLite FTS5, weighted title x8, body x4, symptom x4, aliases x4, fix x2, tags x1. A record found "
         "only by its tag ranks after every content match.",
         f'{d["fetched"]} fetched', "limit x 3", d["fetched"] / f, 0.0, ""),
        ("3", "SCOPE", "Permission - who may see this",
         "A repo's own records pass first and unconditionally. org records continue. Another "
         "repo's records stop here: the curation boundary.",
         f'{d["after_scope"]} survive', f'{d["dropped_scope"]} dropped: other repos',
         d["after_scope"] / f, d["dropped_scope"] / f, "DROPS"),
        ("4", "VALID", "applies_to - the only filter allowed to exclude",
         f'EXCLUSIVE. Set by hand on {d["applies_to_set"]} of {d["corpus"]} records, only where a '
         "lesson is false off-stack. Unset means anywhere, which is why it is safe.",
         f'{d["after_applies"]} survive', f'{d["dropped_applies"]} dropped: off-stack',
         d["after_applies"] / f, d["dropped_applies"] / f, "DROPS"),
        ("5", "SUBJECT", "tags x interests - one shared subject is enough",
         "INCLUSIVE. Untagged always passes. The exclusive version was reverted (REPORT 4d): "
         "it hid 35 of 172 records and the briefed arm then reproduced a defect it dropped.",
         f'{d["after_tags"]} survive', f'{d["dropped_tags"]} dropped: no shared subject',
         d["after_tags"] / f, d["dropped_tags"] / f, "ANY-MATCH"),
        ("6", "FLOOR", "Two shared subject words, or one in the title or symptom, or a one-word alias",
         "A record found by one word in common ('point', 'doc') outside its title and symptom "
         "is left out and counted, unless it links one step to a kept record. Retired leave too.",
         f'{d["after_floor"]} survive', f'{d["weak"]} dropped: one shared word, {d["retired"]} retired',
         d["after_floor"] / f, (d["weak"] + d["retired"]) / f, "DROPS"),
        ("7", "CUTOFF", "The top 12",
         "Ranking already put the best first; the cut keeps the briefing short. The "
         "number cut travels with the result.",
         f'{d["delivered"]} delivered', f'{d["trimmed"]} trimmed',
         d["delivered"] / f, d["trimmed"] / f, "TRUNCATES"),
        ("8", "SHAPE", "Bucket by type, then route to imperatives",
         "Buckets: gates, defects, retractions, tombstones, threat prior-art, rules, decisions, "
         "vocabulary, related context. Stale demotes, never deletes. Then ARM / FIX / AVOID.",
         "gates -> defects+rules", "-> retractions -> tombstones", 0.0, 0.0, ""),
        ("9", "RENDER", "Three surfaces, one pipeline",
         "agent | actions | json. A zero-match result carries the store size, so 'no rules "
         "apply' can never be confused with 'the store is empty'.",
         "hook | MCP | CI", "", 0.0, 0.0, ""),
    ]
    if d.get("hybrid"):
        # The semantic arm: a second candidate source and the fusion, drawn between RANK and
        # SCOPE because that is where ranked_candidates() puts them; the floor gains its line.
        rank = next(i for i, st in enumerate(stages) if st[1] == "RANK")
        stages[rank] = ("2", "RANK", "Full text: fetch 3x more candidates than needed", stages[rank][3],
                        f'{d["lexical"]} fetched', "limit x 3", d["lexical"] / f, 0.0, "")
        stages.insert(rank + 1, (
            "2b", "EMBED", f"The task as one {d['dim']}-dimension vector; the nearest records by cosine",
            "A local static model (potion-retrieval-32M) read from the cache, never the network; "
            "the vectors come from `okl embed`. One matrix product over every record.",
            f'{d["nearest"]} nearest', f'{d["semantic_only"]} not in the full-text list',
            d["nearest"] / f, 0.0, ""))
        stages.insert(rank + 2, (
            "2c", "FUSE", f"Two orders become one: {d['hybrid']} fusion",
            "linear: a convex combination of a rank-normalised full-text score and the min-max "
            "cosine (alpha 0.5). rrf: reciprocal ranks summed (k = 60). Measured in REPORT 4q.",
            f'{d["fetched"]} candidates', "", 1.0, 0.0, ""))
        floor = next(i for i, st in enumerate(stages) if st[1] == "FLOOR")
        st = list(stages[floor])
        st[2] = f"Two shared words, one in the title or symptom, or a cosine at or above {d['line']:.2f}"
        st[3] = (f"Only-by-embedding records count by meaning alone ({d['by_meaning']} kept so). A single "
                 "shared word outside title and symptom is left out and counted, unless it links to a kept record.")
        stages[floor] = tuple(st)
    h = 166 + len(stages) * ROW_H + 60
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
         f'viewBox="0 0 {W} {h}" font-family="{FONT}">',
         f'<rect width="{W}" height="{h}" fill="{PAPER}"/>']
    title = "How an okl briefing gets built" + (" with the semantic arm on" if d.get("hybrid") else "")
    o.append(f'<text x="{PAD}" y="46" font-size="27" font-weight="700" fill="{INK}">'
             f'{escape(title)}</text>')
    sub = (f'{d["corpus"]} records and one task sentence become the {d["limit"]} an agent reads. '
           + ("A local embedding adds candidates by meaning; five stages then narrow them."
              if d.get("hybrid") else "Five stages narrow it; only applies_to may exclude on validity."))
    o.append(f'<text x="{PAD}" y="72" font-size="14" fill="{INK2}">{escape(sub)}</text>')
    for i, ln in enumerate([
        "GENERATED from the live pipeline - docs/render_pipeline_diagram.py",
        f'traced task: "{d["task"]}"',
        f'searched as: "{d["query"]}"',
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
        # Truncating here silently dropped "(REPORT 4d)." from stage 4 for as long as
        # this file has existed, and nothing said so. A generator that quietly discards
        # content it was given is the same failure as a check that reports success having
        # written nothing — so refuse instead, and let whoever adds the text shorten it.
        if len(lines) > MAX_BODY_LINES:
            raise SystemExit(
                f"ABORT: stage {n!r} body wraps to {len(lines)} lines, budget is "
                f"{MAX_BODY_LINES} at ROW_H={ROW_H}. Shorten it, or raise both together — "
                "do not let the render drop the tail.")
        for i, ln in enumerate(lines):
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
    fns = ["src/okl/core.py briefing_terms() / ranked_candidates() / _live_hits() / _in_scope() / _apply_floor() . "
           "src/okl/store.py search()" + (" . src/okl/semantic.py search()" if d.get("hybrid") else ""),
           "regenerate: python3 docs/render_pipeline_diagram.py" + (f" --hybrid {d['hybrid']}" if d.get("hybrid") else "")]
    for i, ln in enumerate(fns):
        o.append(f'<text x="{PAD}" y="{h - 40 + i * 14}" font-size="11" font-family="{MONO}" fill="{INK3}">{escape(ln)}</text>')
    o.append("</svg>")
    return "\n".join(o) + "\n"


def main() -> int:
    """Trace the pipeline, then write the SVG (or print the counts with --json)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit traced counts, render nothing")
    ap.add_argument("--hybrid", choices=["rrf", "linear"], default=None,
                    help="trace with the semantic arm on (needs the cached model); the render goes to "
                         "docs/okl-retrieval-pipeline-hybrid.svg unless --out says otherwise")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out_path = a.out or str(REPO / "docs" / ("okl-retrieval-pipeline-hybrid.svg" if a.hybrid else "okl-retrieval-pipeline.svg"))
    d = trace(hybrid=a.hybrid)
    if a.json:
        print(json.dumps(d, indent=2))
        return 0
    Path(out_path).write_text(render(d))
    # --out may point outside the repo (the freshness test regenerates to a scratch dir),
    # so relative_to is a best effort, not a guarantee.
    try:
        shown = Path(out_path).relative_to(REPO)
    except ValueError:
        shown = Path(out_path)
    print(f"wrote {shown}  "
          f"({d['corpus']} records -> {d['fetched']} -> {d['after_scope']} -> "
          f"{d['after_applies']} -> {d['after_tags']} -> {d['delivered']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
