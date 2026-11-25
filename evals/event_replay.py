#!/usr/bin/env python3
"""Exploratory: on §4bj's graded broken tasks, would an event read from a lesson's own text have
chosen the lesson the change broke, and how many other lessons with it? (REPORT §4bm)

The review after writing has a model pick the lessons to check, and that pick is where most of its
losses start (REPORT §4bk). A rule that says by itself when it applies would need no pick. This asks
how far that reaches with no model call and nothing authored: only what a lesson already names in
its full text, as the review held it for the task.

A lesson names two kinds of thing a program can look for in a change:

- **a path**: something with a slash, or a file name with a known extension;
- **a piece of code**: a dotted name, a call, an ALL_CAPS, snake_case or CamelCase name, a `--flag`.

An event fires for a lesson on a change when a path it names is a changed file (or that file's
folder, or its bare name), or when a piece of code it names appears in a line the change added.
For each kind it counts the tasks where the right lesson fired, and how many of the lessons in
scope fired on the same change: a rule that fires for most lessons has chosen nothing.

It reads the change as §4bl's pick was given it (base to frozen commit, cut to the same size), so a
path past the cut is not seen. With `--receipt` it also counts, in the local store as it is today,
the right lessons that have an observed check: a count of the store now, not at the time of each
task. It calls no model and changes nothing.

    python3 evals/event_replay.py [--receipt]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import lesson_finding as lf
import pick_prefilter as pp
import review_graded as g
import run_guard

EXT = r"(?:py|sh|md|json|jsonl|ya?ml|toml|html|svg|txt|cfg|ini|lock)"
PATH = re.compile(rf"(?<![\w/.:-])((?:[\w.*-]+/)+[\w.*-]*|[\w-]+\.{EXT})(?![\w-])")
CODE = [re.compile(p) for p in (
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b",          # a dotted.name
    r"\b[A-Za-z_]\w{2,}(?=\()",                       # a call
    r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b",                 # an ALL_CAPS_NAME
    r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b",                 # a snake_case name
    r"\b[A-Z][a-z0-9]+[A-Z]\w*\b",                    # a CamelCase name
    r"(?<![\w-])--[a-z][a-z0-9-]+",                   # a --flag
)]
NOT_A_PATH = {"e.g", "i.e", "etc.", "vs.", "and/or", "w/o"}
ARMS = ("governs today", "paths", "code", "either")
MODEL_PICK_RECEIPT = "lesson-finding-20261117-0441.json"      # §4bl: the model's pick
WORDS_RECEIPT = "pick-prefilter-20261120-0624.json"           # #497: the change's words, ranked


def named_paths(text: str) -> set[str]:
    """The paths a lesson's text names: with a slash, or a file name with a known extension."""
    out = set()
    for m in PATH.finditer(text):
        t = m.group(1).strip("/.")
        if len(t) > 3 and t.lower() not in NOT_A_PATH and not re.fullmatch(r"[\d./-]+", t) and "//" not in m.group(1):
            out.add(t)
    return out


def named_code(text: str) -> set[str]:
    """The pieces of code a lesson's text names, longer than four characters; a file name is a path."""
    out = set()
    for rx in CODE:
        for m in rx.finditer(text):
            t = m.group(0)
            if len(t) > 4 and not re.fullmatch(rf"[\w-]+\.{EXT}", t):
                out.add(t)
    return out


def changed_paths(diff: str) -> list[str]:
    """Each file the change leaves in place, from the diff's own headers."""
    return sorted(set(re.findall(r"(?m)^\+\+\+ b/(.+)$", diff)))


def added_lines(diff: str) -> str:
    """The text of the lines the change added."""
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def path_fires(named: set[str], paths: list[str]) -> bool:
    """Whether a named path is a changed file, the folder of one, or the bare name of one; `*` in
    a name stands for any run of characters within one path segment."""
    for t in named:
        rx = re.compile(re.escape(t).replace(r"\*", r"[^/]*")) if "*" in t else None
        for p in paths:
            if rx is not None:
                if rx.search(p):
                    return True
            elif p == t or p.endswith("/" + t) or p.startswith(t + "/") or ("/" not in t and Path(p).name == t):
                return True
    return False


def code_fires(named: set[str], added: str) -> bool:
    """Whether a named piece of code appears whole in a line the change added."""
    return any(re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", added) for t in named)


def one(task: dict[str, Any]) -> dict[str, Any]:
    """For one task: under each arm, whether the right lesson fired and how many lessons fired."""
    ids, governing, text = pp.listed(task)
    diff = lf.diff(task)
    paths, added = changed_paths(diff), added_lines(diff)
    fired: dict[str, set[str]] = {"governs today": set(governing), "paths": set(), "code": set()}
    for i in ids:
        if path_fires(named_paths(text[i]), paths):
            fired["paths"].add(i)
        if code_fires(named_code(text[i]), added):
            fired["code"].add(i)
    fired["either"] = fired["paths"] | fired["code"]
    row: dict[str, Any] = {"id": task["id"], "okl_commit": run_guard.commit(), "right": task["lesson"],
                           "lessons": len(ids), "changed_files": len(paths)}
    for arm in ARMS:
        row[f"{arm}:right"] = task["lesson"] in fired[arm]
        row[f"{arm}:fired"] = len(fired[arm])
    return row


def store_today(rights: list[str]) -> dict[str, Any] | None:
    """Of the right lessons, those with an observed check and those with files in the local store
    as it is now. Read-only, so an older store is not upgraded by a look; None where there is none."""
    common = g.o.git("rev-parse", "--git-common-dir").strip()
    top = Path(common).resolve().parent if Path(common).is_absolute() else (g.REPO / common).resolve().parent
    db = top / ".okl" / "okl.db"
    if not db.is_file():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = {r[0]: r[1:] for r in con.execute("select id, verified_by, files from node")}
    finally:
        con.close()
    return {"distinct_right_lessons": len(rights),
            "with_an_observed_check": sorted(i for i in rights if i in rows and rows[i][0]),
            "with_files": sorted(i for i in rights if i in rows and rows[i][1] not in (None, "", "[]")),
            "not_in_the_store": sorted(i for i in rights if i not in rows)}


def main() -> int:
    """Fire, count, print; with --receipt, write the rows and rates to evals/results/."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    run = run_guard.start()
    rows = [one(t) for t in lf.tasks()]
    n = len(rows)
    rates = {arm: {"right_fired": sum(r[f"{arm}:right"] for r in rows),
                   "rate": round(sum(r[f"{arm}:right"] for r in rows) / n, 3),
                   "fired_median": median(r[f"{arm}:fired"] for r in rows),
                   "fired_min": min(r[f"{arm}:fired"] for r in rows),
                   "fired_max": max(r[f"{arm}:fired"] for r in rows)} for arm in ARMS}
    print(f"{n} tasks; lessons in scope: median {median(r['lessons'] for r in rows)}; "
          f"changed files: median {median(r['changed_files'] for r in rows)}")
    print(f"{'event read from the lesson':<30}{'right lesson fired':<22}lessons fired per change: median (range)")
    for arm in ARMS:
        a = rates[arm]
        print(f"{arm:<30}{a['right_fired']} of {n} = {a['rate']:<12}{a['fired_median']} ({a['fired_min']} to {a['fired_max']})")
    results = g.REPO / "evals" / "results"
    pick = json.loads((results / MODEL_PICK_RECEIPT).read_text())["reach"]
    words = json.loads((results / WORDS_RECEIPT).read_text())["rates"]["words"]
    print(f"for comparison: a model's ten from the full list {pick['n10']['rate']}, its thirty {pick['n30']['rate']} "
          f"({MODEL_PICK_RECEIPT}); the change's words ranked, top 10 {words['top10']}, top 50 {words['top50']} "
          f"({WORDS_RECEIPT})")
    today = store_today(sorted({r["right"] for r in rows}))
    if today:
        print(f"right lessons: {today['distinct_right_lessons']} distinct; in the store today "
              f"{len(today['with_an_observed_check'])} have an observed check and {len(today['with_files'])} have files")
    if args.receipt:
        out = results / f"event-replay-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        receipt = run.stamp({"written_by": "evals/event_replay.py", "at": g.o.git("rev-parse", "HEAD").strip(),
                             "tasks": n, "run_commits": sorted({r["okl_commit"] for r in rows}), "rates": rates,
                             "store_today": today,
                             "compared_with": {MODEL_PICK_RECEIPT: {"n10": pick["n10"]["rate"], "n30": pick["n30"]["rate"]},
                                               WORDS_RECEIPT: words},
                             "rows": rows})
        out.write_text(json.dumps(receipt, indent=1) + "\n")
        print(f"wrote {out.relative_to(g.REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
