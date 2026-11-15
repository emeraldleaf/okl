#!/usr/bin/env python3
"""REPORT §4bg: the nine other lessons each task's list holds, built as §4ax built its own.

What okl's search (`core.ranked_candidates`, linear) ranks highest for the task's own words, among the
lessons as they stood at the frozen commit: created by then, live, advice, never the right lesson, and
none citing the task's PR or its grader. §4ax built its lists by hand and kept only the result; this
keeps the builder, so the lists can be rebuilt and checked.

    python3 evals/replay_lists_4bg.py [--write]

Reads a read-only copy of this checkout's store; writes evals/replay-lists-4bg.json with --write.
The store keeps no history of a lesson's words or status, so "as they stood" means the lessons that
existed then, as they read and stand today: one edited since reads as edited, and one retired since
is left out though it was live then. The tasks' own lessons are treated the same way (their text is
today's, with this task's fix removed), and REPORT §4bg says so.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import sandbox as sb

from okl import core
from okl.drift import _NOT_ADVICE
from okl.store import RETIRED_STATUSES, Node, Store

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "evals" / "replay-tasks-4bg.json"
LISTS = REPO / "evals" / "replay-lists-4bg.json"
STORE = REPO / ".okl" / "okl.db"
OTHERS, FETCH = 9, 400


def words(task: dict) -> str:
    """The change's title and its issues, as the author had them (outcome_replay.task_words)."""
    return "\n\n".join([task["title"], *(f"{i['title']}\n{i['body']}" for i in task["issues"])]).strip()


def text_of(node: Node) -> str:
    """A lesson as an arm is shown it: the shape of the tasks' own lesson_text."""
    lines = [f"[{node.id}] {node.type} · {node.title}"]
    if (node.symptom or "").strip():
        lines.append(f"symptom: {node.symptom.strip()}")
    if (node.fix or "").strip():
        lines.append(f"fix: {node.fix.strip()}")
    return "\n".join(lines)


def frozen_ms(commit: str) -> int:
    """When the frozen commit was made, in the store's epoch milliseconds."""
    out = subprocess.run(["git", "-C", str(REPO), "show", "-s", "--format=%ct", commit],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip()) * 1000


def as_they_stood(src: Path, dst: Path, before_ms: int) -> None:
    """`dst`: the store with only the lessons that existed at `before_ms`, retired ones and records that
    are not advice left out, so neither the search nor a list can reach them."""
    with contextlib.closing(sb.connect(src)) as source, contextlib.closing(sb.connect(dst)) as con:
        source.backup(con)
        con.execute("delete from node where type != 'Vocabulary' and created_at > ?", (before_ms,))
        marks = ",".join("?" * len(RETIRED_STATUSES))
        con.execute(f"delete from node where status in ({marks})", tuple(RETIRED_STATUSES))   # noqa: S608
        kinds = ",".join("?" * len(_NOT_ADVICE))
        con.execute(f"delete from node where type in ({kinds})", tuple(_NOT_ADVICE))   # noqa: S608
        con.execute("delete from node_fts where id not in (select id from node)")
        con.execute("delete from embedding where node_id not in (select id from node)")
        con.execute("delete from edge where src not in (select id from node) or dst not in (select id from node)")
        con.commit()


def build(task: dict, snapshot: Path, side: Path) -> dict:
    """One task's list: the nine others, and where the right lesson stands in the same search."""
    db = side / f"store-{task['id']}.db"
    as_they_stood(snapshot, db, frozen_ms(task["frozen"]))
    found = core.ranked_candidates(Store(f"sqlite:///{db}"), words(task), FETCH, "linear")
    if found.note:
        raise SystemExit(f"{task['id']}: the semantic arm did not run ({found.note}); not building a "
                         "keyword-only list")
    ids = [n.id for n in found.nodes]
    others = []
    for n in found.nodes:
        text = text_of(n)
        if n.id == task["lesson"] or f"#{task['pr']}" in text or task["grader"] in text:
            continue
        others.append({"id": n.id, "text": text})
        if len(others) == OTHERS:
            break
    if len(others) < OTHERS:
        raise SystemExit(f"{task['id']}: only {len(others)} other lessons reachable")
    rank = ids.index(task["lesson"]) + 1 if task["lesson"] in ids else None
    return {"others": others, "target_rank_in_search": rank, "candidates": len(ids)}


def main() -> int:
    """Build every task's list; print a summary, and write the file with --write."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    tasks = json.loads(TASKS.read_text())
    with tempfile.TemporaryDirectory(prefix="okl-lists-") as side:
        snapshot = Path(side) / "store.db"
        sb.copy_sqlite(STORE, snapshot)
        lists = {t["id"]: build(t, snapshot, Path(side)) for t in tasks}
    for tid, row in lists.items():
        print(f"{tid}: right lesson ranked {row['target_rank_in_search']} of {row['candidates']}; "
              f"others {[o['id'] for o in row['others']]}")
    if args.write:
        LISTS.write_text(json.dumps(lists, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {LISTS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
