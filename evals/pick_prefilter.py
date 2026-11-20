"""#497, exploratory: can a mechanical ranking against the change hand the review's pick a short list?

The review after writing has a model pick ten lessons from every lesson in scope, one line each. Given
that list and the diff, its ten held the right lesson on 0.628 of §4bj's 43 graded broken tasks and its
thirty on 0.791 (REPORT §4bl). The list is four pages at 339 lessons and will not fit a shared store.
This measures, with no model call, how often the right lesson is among the top K when every lesson is
ranked against the change:

- **words**: BM25 of the lesson's full text against the change's words;
- **meaning**: the cosine of the lesson's embedding with the change's, the highest over the change's
  hunks, using okl's own model (`semantic.MODEL_ID`);
- **fused**: reciprocal rank fusion of the two.

Lessons that govern a changed file are kept whatever their rank, as the review lists them first; they
take places in the K. It decides whether a pre-filter is worth building, and says nothing of what a
review session then does with the shorter list.

    python3 evals/pick_prefilter.py [--receipt]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

import lesson_finding as lf
import review_graded as g
import run_guard

from okl import semantic, warm

KS = (10, 30, 50, 100)
MODEL_PICK_RECEIPT = "lesson-finding-20261117-0441.json"      # §4bl: the model's pick this is held against
HUNK_CHARS = 4000        # a hunk past this is cut for the warm model, which reads tokens, not a bag of words
_WARM: dict[str, list[float]] = {}
RRF_K = 60
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
LINE = re.compile(r"^- \[([^\]]+)\] (.*)$")


def words(text: str) -> list[str]:
    """Identifier-like words, lower-cased, with snake_case and camelCase parts as words too."""
    out = []
    for w in WORD.findall(text):
        out.append(w.lower())
        parts = [p for p in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", w) if len(p) > 2]
        if len(parts) > 1:
            out += [p.lower() for p in parts]
    return out


def listed(task: dict[str, Any]) -> tuple[list[str], set[str], dict[str, str]]:
    """The review's lessons for a task in its order, those that govern a changed file, and each one's
    text: its full text where the build wrote one, else its line."""
    ids, governing, text = [], set(), {}
    in_governing = False
    for line in lf.lessons_section(task).splitlines():
        if line.startswith("### "):
            in_governing = "govern a file" in line
            continue
        m = LINE.match(line)
        if not m:
            continue
        ids.append(m[1])
        if in_governing:
            governing.add(m[1])
        full = g.BUILT / task["id"] / "lessons" / f"{m[1].replace('/', '_')}.md"
        text[m[1]] = full.read_text() if full.exists() else m[2]
    return ids, governing, text


def hunks(diff: str) -> list[str]:
    """The diff cut at each hunk header, so a long change is many short texts, not one average."""
    parts = [p for p in re.split(r"(?m)^(?=@@ |diff --git )", diff) if p.strip()]
    return parts or [diff]


def bm25(query: list[str], docs: dict[str, list[str]]) -> dict[str, float]:
    """BM25 with the query's words counted once each (a diff repeats its identifiers)."""
    n = len(docs)
    avg = sum(len(d) for d in docs.values()) / max(n, 1)
    df = Counter(w for d in docs.values() for w in set(d))
    q = set(query)
    scores = {}
    for doc_id, d in docs.items():
        tf = Counter(d)
        s = 0.0
        for w in q & tf.keys():
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        scores[doc_id] = s
    return scores


def ranked(scores: dict[str, float], order: list[str]) -> list[str]:
    """Ids by score, highest first, ties in the review's own order."""
    place = {i: n for n, i in enumerate(order)}
    return sorted(scores, key=lambda i: (-scores[i], place[i]))


def with_governing(order: list[str], governing: set[str]) -> list[str]:
    """Lessons that govern a changed file first, then the ranking."""
    return [i for i in order if i in governing] + [i for i in order if i not in governing]


def warm_cosines(encode: Any, ids: list[str], text: dict[str, str], parts: list[str]) -> dict[str, float]:
    """Each lesson's highest cosine with a hunk under the warm model (EmbeddingGemma), the lessons
    encoded as documents once and the hunks as queries."""
    todo = [text[i] for i in ids if text[i] not in _WARM]
    _WARM.update(zip(todo, encode(todo, "doc"), strict=True))
    change = encode([p[:HUNK_CHARS] for p in parts], "query")
    return {i: max(sum(a * b for a, b in zip(_WARM[text[i]], c, strict=True)) for c in change) for i in ids}


def fuse(orders: list[list[str]], ids: list[str]) -> list[str]:
    """Reciprocal rank fusion of several rankings of the same ids."""
    rrf = {i: 0.0 for i in ids}
    for order in orders:
        for n, i in enumerate(order, 1):
            rrf[i] += 1 / (RRF_K + n)
    return ranked(rrf, ids)


def one(task: dict[str, Any], model: Any, encode: Any = None) -> dict[str, Any]:
    """The right lesson's place under each arm for one task, with and without governing lessons first."""
    ids, governing, text = listed(task)
    diff = lf.diff(task)
    by_words = ranked(bm25(words(diff), {i: words(text[i]) for i in ids}), ids)
    parts = hunks(diff)
    change = semantic.encode(model, parts)
    lessons = semantic.encode(model, [text[i] for i in ids])
    cosine = {i: max(sum(a * b for a, b in zip(v, c, strict=True)) for c in change) for i, v in zip(ids, lessons, strict=True)}
    by_meaning = ranked(cosine, ids)
    arms = {"words": by_words, "meaning": by_meaning, "fused": fuse([by_words, by_meaning], ids)}
    if encode is not None:
        by_warm = ranked(warm_cosines(encode, ids, text, parts), ids)
        arms |= {"warm": by_warm, "fused-warm": fuse([by_words, by_warm], ids)}
    right = task["lesson"]
    row: dict[str, Any] = {"id": task["id"], "okl_commit": run_guard.commit(), "lessons": len(ids),
                           "governing": len(governing),
                           "right_governs": right in governing, "hunks": len(parts)}
    for name, order in arms.items():
        row[name] = order.index(right) + 1
        row[name + "+governing"] = with_governing(order, governing).index(right) + 1
    return row


def main() -> int:
    """Rank, count, print; with --receipt, write the rows and rates to evals/results/."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", action="store_true")
    ap.add_argument("--warm", action="store_true", help="add the warm model's arms (minutes, not seconds)")
    args = ap.parse_args()
    model = semantic.load_model()
    encode = warm.load_model() if args.warm else None
    rows = []
    for t in lf.tasks():
        rows.append(one(t, model, encode))
        print(f"{t['id']} done", file=sys.stderr, flush=True)
    arms = [k for k in rows[0] if k not in ("id", "okl_commit", "lessons", "governing", "right_governs", "hunks")]
    rates = {a: {f"top{k}": round(sum(r[a] <= k for r in rows) / len(rows), 3) for k in KS}
             | {"median_rank": median(r[a] for r in rows)} for a in arms}
    print(f"{len(rows)} tasks; lessons listed: median {median(r['lessons'] for r in rows)}; "
          f"the right lesson governs a changed file on {sum(r['right_governs'] for r in rows)}")
    print(f"{'arm':<20}" + "".join(f"top{k:<6}" for k in KS) + "median rank")
    for a in arms:
        print(f"{a:<20}" + "".join(f"{rates[a][f'top{k}']:<9}" for k in KS) + str(rates[a]["median_rank"]))
    was = json.loads((g.REPO / "evals" / "results" / MODEL_PICK_RECEIPT).read_text())["reach"]
    print(f"for comparison (REPORT §4bl, {MODEL_PICK_RECEIPT}): a model's ten from the full list "
          f"{was['n10']['rate']}, its thirty {was['n30']['rate']}")
    if args.receipt:
        out = g.REPO / "evals" / "results" / f"pick-prefilter-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        out.write_text(json.dumps({"written_by": "evals/pick_prefilter.py", "at": g.o.git("rev-parse", "HEAD").strip(),
                                   "model": semantic.MODEL_ID, "warm_model": warm.MODEL_ID if args.warm else None,
                                   "run_commits": sorted({r["okl_commit"] for r in rows}), "rates": rates, "rows": rows}, indent=1) + "\n")
        print(f"wrote {out.relative_to(g.REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
