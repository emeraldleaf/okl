#!/usr/bin/env python3
"""Label every lesson against every task of REPORT §4al: which lessons did each real change need?

For each task in evals/realwork/tasks.jsonl, every lesson the store held when its code was first
written is shown to the judge, twenty at a time, with the change (its diff, rebuilt from the
recorded shas and cut at 60,000 characters), the issues it closes and its title. The judge answers
each lesson needed, related, no or unsure, with the line it rests on. Every lesson must get exactly
one answer: the ones a reply leaves out are asked once more on their own, and any still unanswered
are recorded as such and reported.

The judge is pinned: the model and the sha256 of the prompt go in every label and in the receipt, so
a later comparison can refuse a different judge. It runs text-only from an empty folder, with
--restricted (no settings file, so no hook) and no tools. Labels are written as each batch lands,
and a re-run skips the batches already labelled.

    python3 evals/realwork_label.py [--workers 3] [--limit-tasks N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "evals" / "realwork" / "tasks.jsonl"
LABELS = REPO / "evals" / "realwork" / "labels.jsonl"
STORE = REPO / "evals" / "bench" / "private" / "realwork" / "store.db"
MODEL = "opus"
JUDGE = ["claude", "-p", "--model", MODEL, "--restricted", "--strict-mcp-config", "--output-format", "json",
         "--tools", ""]
BATCH, CUT, TIMEOUT = 20, 60_000, 600
VERDICTS = ("needed", "related", "no", "unsure")
PROMPT = """You are labelling which lessons a software change needed. A team keeps lessons: rules, past
defects and decisions it learned. Below is a change as it was first written (a git diff), the issue
it was written for if there is one, its title, and some of the team's lessons.

For each lesson, decide:
- "needed": following the lesson would change this code, or the lesson warns of a defect this change
  has or risks. It applies to what the change does.
- "related": the lesson is about the same subject, but nothing in this change would differ for it.
- "no": it does not apply to this change.
- "unsure": you cannot decide.

Judge each lesson on its own, against what the change does. A lesson can be needed even though the
change shares none of its words, and sharing words does not make it needed. Most lessons will be "no".

TITLE: {title}

ISSUE:
{issues}

CHANGE:
{change}

LESSONS:
{lessons}

Answer with one JSON array and nothing else, one object per lesson, every lesson exactly once:
[{{"id": "<lesson id>", "verdict": "needed|related|no|unsure", "evidence": "the line of the change or sentence of the issue it rests on, or empty"}}]"""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
_lock = threading.Lock()


def git(*args: str) -> str:
    """git's stdout in this repository."""
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout


def lesson_text(db: Path) -> dict[str, str]:
    """Each lesson's text as the judge sees it: id, type, title, symptom, fix, body (cut)."""
    con = sqlite3.connect(db)
    out = {}
    for i, t, title, symptom, fix, body in con.execute(
            "select id, type, title, symptom, fix, body from node"):
        parts = [f"[{i}] ({t}) {title or ''}"]
        if symptom:
            parts.append(f"  symptom: {symptom}")
        if fix:
            parts.append(f"  fix: {fix}")
        if body:
            parts.append(f"  body: {body[:600]}")
        out[i] = "\n".join(parts)
    con.close()
    return out


def last_array(text: str) -> list | None:
    """The judge's answer in `text`: the largest JSON array of objects carrying an "id", or None.
    Not merely the last array: evidence that quotes a list ("[4, 11]") parses as one, and taking it
    left a whole batch unanswered in the pilot."""
    dec, found = json.JSONDecoder(), None
    for m in re.finditer(r"\[", text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if (isinstance(obj, list) and obj and all(isinstance(x, dict) and "id" in x for x in obj)
                and (found is None or len(obj) >= len(found))):
            found = obj
    return found


def ask(prompt: str, room: Path) -> tuple[list | None, str]:
    """The judge's array for `prompt`, and an error when there is none."""
    try:
        p = subprocess.run(JUDGE, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=room)
    except subprocess.TimeoutExpired:
        return None, f"no answer in {TIMEOUT} s"
    try:
        result = json.loads(p.stdout).get("result") or ""
    except ValueError:
        result = p.stdout
    got = last_array(result)
    return (got, "") if got is not None else (None, f"no array (exit {p.returncode}): {p.stderr.strip()[-160:]}")


def label_batch(task: dict, ids: list[str], texts: dict[str, str], change: str, room: Path) -> list[dict]:
    """Labels for `ids` on `task`: one per id, asking once more for any the first reply left out."""
    issues = "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in task["issues"]) or "(none)"
    out: dict[str, dict] = {}
    pending, tries = list(ids), 0
    while pending and tries < 2:
        tries += 1
        prompt = PROMPT.format(title=task["title"], issues=issues, change=change,
                               lessons="\n\n".join(texts[i] for i in pending))
        got, err = ask(prompt, room)
        for item in got or []:
            if isinstance(item, dict) and item.get("id") in pending and item.get("verdict") in VERDICTS:
                out[item["id"]] = {"verdict": item["verdict"], "evidence": str(item.get("evidence") or "")[:400]}
        pending = [i for i in pending if i not in out]
        if err and not got:
            for i in pending:
                out.setdefault(i, {"verdict": None, "evidence": "", "error": err})
    for i in pending:
        out.setdefault(i, {"verdict": None, "evidence": "", "error": "not answered after a second ask"})
    return [{"pr": task["pr"], "lesson": i, **out[i], "model": MODEL, "prompt": PROMPT_SHA} for i in ids]


def main() -> int:
    """Label every pending batch; print the receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit-tasks", type=int, default=None, help="label only the first N tasks (a pilot)")
    args = ap.parse_args()
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()][: args.limit_tasks]
    texts = lesson_text(STORE)
    done = set()
    if LABELS.exists():
        for line in LABELS.read_text().splitlines():
            r = json.loads(line)
            if r.get("verdict") and r.get("prompt") == PROMPT_SHA:
                done.add((r["pr"], r["lesson"]))
    jobs = []
    for t in tasks:
        diff = git("diff", f"{t['base']}..{t['commit']}")
        change = diff if len(diff) <= CUT else diff[:CUT] + f"\n[... cut: {len(diff) - CUT} more characters]"
        todo = [i for i in sorted(t["lessons"]) if (t["pr"], i) not in done and i in texts]
        jobs += [(t, todo[k:k + BATCH], change) for k in range(0, len(todo), BATCH)]
    print(f"{len(tasks)} tasks · {len(jobs)} batches to label · judge {MODEL} prompt {PROMPT_SHA}", file=sys.stderr)
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="okl-4al-judge-") as room:
        def run(job: tuple) -> None:
            t, ids, change = job
            rows = label_batch(t, ids, texts, change, Path(room))
            with _lock, LABELS.open("a") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    counts[str(r["verdict"])] = counts.get(str(r["verdict"]), 0) + 1
            print(f"  #{t['pr']} {len(ids)} labelled · totals {counts}", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            list(pool.map(run, jobs))
    receipt = {"section": "4al", "step": "labels", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
               "judge": JUDGE, "prompt_sha": PROMPT_SHA, "tasks": len(tasks), "batches": len(jobs),
               "this_run": counts}
    print(json.dumps(receipt, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
