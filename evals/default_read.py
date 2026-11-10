#!/usr/bin/env python3
"""REPORT §4au: should the review after writing be on by default? A quick read on 20 unseen tasks.

Ten of §4aq's tasks whose change broke a lesson and ten that broke none. For each, one Sonnet
session in a copy of the repository at the task's commit gets the change, the output `okl check
--change` gives for it, and every lesson's full text as a file (standing in for `okl show`), and
follows the shipped steps. It says which lessons it would change code for; the key says whether
they were broken.

    python3 evals/default_read.py run       # the 20 reviews, resumable
    python3 evals/default_read.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import explain_search as es
import lesson_review as lr
import realwork_label as rl
import review_action as ra
import review_repo as rp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from okl import core
from okl.store import Store

PER_ARM, SEED, WORKERS, TIMEOUT, STOP_AFTER_EMPTY = 10, 4, 3, 1500, 6
REACH_BAR, FALSE_ALARM_BAR = 0.30, 1
OUT = lr.PRIVATE / "default-read-4au.jsonl"
LESSON_DIR, LIST_FILE, CHANGE_FILE = "review-lessons", "REVIEW.md", "CHANGE.diff"
STEPS = [   # the steps as §4au ran them (prompt a394d83ab20f46e4), frozen so its receipt stays reproducible
    'Say what the changed code does, one mechanism per sentence: what it calls and from where, what it reads and writes (files, databases, environment, network, output), what it assumes, how it fails and what it returns or prints then, what its tests check and with what data, and what the docs it changes now claim.',
    'From the lessons in REVIEW.md, pick the ten this change is most likely to break: the ones about something the code does. Any that govern a file it touched are listed first, and are read as well.',
    'Read each in full at review-lessons/<id>.md and check the code against all of it.',
    'You cannot change code here: list each lesson you would change code for, and what you would change. Where a lesson does not apply, or the code already does what it says, leave the code alone.',
    'Say which lessons you checked, what you changed for each, and why the rest needed nothing.',
]
PROMPT = f"""You just wrote the change in {CHANGE_FILE}. Your working directory is the repository with that change applied. Before you finish, check the code you wrote against this repository's lessons. {LIST_FILE} is what `okl check --change` printed for this change: the steps, the changed files, and every lesson in scope, one line each.

""" + "\n".join(f"{i}. {s}" for i, s in enumerate(STEPS, 1)) + """

Answer with one JSON object and nothing after it:
{"explained": ["one sentence per mechanism", ...], "picked": ["lesson id", ...], "breaks": [{"id": "lesson id", "why": "what in the code breaks it", "change": "what you would change"}]}
"breaks" holds only the lessons the code breaks and that you would change code for; an empty list is a fine answer."""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
assert PROMPT_SHA == "a394d83ab20f46e4", "the §4au prompt changed after its run"
SONNET = rp.SONNET_READS


def chosen() -> list[tuple[str, dict]]:
    """Ten tasks that broke a lesson and ten that broke none, drawn in pull-request order."""
    key, tasks = es.key_of("test"), sorted(es.tasks_of("test"), key=lambda t: t["pr"])
    broke = [t for t in tasks if any(key.get((t["pr"], i)) == "broken" for i in t["lessons"])]
    clean = [t for t in tasks if t not in broke]
    rng = random.Random(SEED)  # noqa: S311 - a seeded draw, not a secret
    return [("broke", t) for t in rng.sample(broke, PER_ARM)] + [("clean", t) for t in rng.sample(clean, PER_ARM)]


def full_text(db: Path) -> dict[str, str]:
    """Each lesson as `okl show` gives its words: title, symptom, fix, body and governed files."""
    con = sqlite3.connect(db)
    try:
        rows = con.execute("select id, type, title, symptom, fix, body, files from node").fetchall()
    finally:
        con.close()
    out = {}
    for i, typ, title, symptom, fix, body, files in rows:
        parts = [f"[{i}] {typ} · {title or ''}"]
        parts += [f"{name}: {v}" for name, v in (("symptom", symptom), ("fix", fix), ("files", files), ("body", body)) if v]
        out[i] = "\n".join(parts) + "\n"
    return out


def review_text(task: dict, db: Path, files: list[str]) -> str:
    """What `okl check --change` prints for the task, from its store as it stood."""
    nodes = Store(f"sqlite:///{db}").all_nodes()
    lessons = core.review_menu(nodes, "okl", None)
    listed = {e["id"] for e in lessons}
    governed = sorted(n.id for n in core.governing(nodes, "okl", set(files)) if n.id in listed)
    return core.render_review({"repo": "okl", "base": "main", "merge_base": task["base"], "files": files,
                               "governing": governed, "lessons": lessons})


def changed_files(diff: str) -> list[str]:
    """The paths a unified diff changes, as `okl check --change` lists them."""
    out = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
            if path not in out:
                out.append(path)
    return sorted(out)


def answer_in(text: str) -> dict | None:
    """The last JSON object in `text` that carries "breaks"."""
    decoder, found = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, dict) and "breaks" in obj:
                found = obj
    return found


def review_one(arm: str, task: dict) -> dict | None:
    """One review session; None when it gave no answer (a usage limit looks like this)."""
    diff = ra.whole(task)
    with tempfile.TemporaryDirectory(prefix="okl-4au-store-") as side, rp.checkout(task) as room:
        db = es.store_for("test", task, Path(side))
        (room / CHANGE_FILE).write_text(diff)
        (room / LIST_FILE).write_text(review_text(task, db, changed_files(diff)))
        texts = full_text(db)
        (room / LESSON_DIR).mkdir()
        for i in task["lessons"]:
            (room / LESSON_DIR / f"{i.replace('/', '_')}.md").write_text(texts.get(i, f"[{i}] (no text)\n"))
        start = time.monotonic()
        try:
            p = subprocess.run(SONNET, input=PROMPT, capture_output=True, text=True, timeout=TIMEOUT, cwd=room, env=rp.ENV)
        except subprocess.TimeoutExpired:
            return None
    try:
        reply = json.loads(p.stdout)
    except ValueError:
        return None
    got = answer_in(reply.get("result") or "")
    if got is None:
        return None
    u = reply.get("usage") or {}
    return {"pr": task["pr"], "arm": arm, "prompt": PROMPT_SHA, "answer": got, "seconds": round(time.monotonic() - start, 1),
            "tokens": {"input": u.get("input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
                       "cache_write": u.get("cache_creation_input_tokens", 0), "output": u.get("output_tokens", 0)},
            "api_priced_usd": reply.get("total_cost_usd", 0)}


def done() -> dict[int, dict]:
    """Every review kept under this prompt, by pull request."""
    if not OUT.exists():
        return {}
    return {r["pr"]: r for r in map(json.loads, OUT.read_text().splitlines()) if r.get("prompt") == PROMPT_SHA}


def run() -> int:
    """Review each chosen task that has no review yet; stop at what looks like a usage limit."""
    have = done()
    todo = [(arm, t) for arm, t in chosen() if t["pr"] not in have]
    print(f"{len(todo)} reviews to run with prompt {PROMPT_SHA}", file=sys.stderr, flush=True)
    empty = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(review_one, arm, t): t["pr"] for arm, t in todo}
        for n, f in enumerate(as_completed(futures), 1):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush(); empty = 0
            else:
                empty += 1
                print(f"  #{futures[f]}: no answer", file=sys.stderr, flush=True)
                if empty >= STOP_AFTER_EMPTY:
                    for w in futures:
                        w.cancel()
                    sys.exit(f"{empty} reviews in a row gave no answer, which is what a usage limit looks like; rerun to resume")
            print(f"  {n}/{len(todo)}", file=sys.stderr, flush=True)
    missing = [t["pr"] for _, t in chosen() if t["pr"] not in done()]
    print(json.dumps({"prompt": PROMPT_SHA, "missing": missing}))
    return 0 if not missing else 2


def boot(values: list[tuple[int, int]], rng: random.Random) -> list[float]:
    """A bootstrap interval over tasks for a ratio of summed hits to summed totals."""
    vals = []
    for _ in range(ba.BOOT):
        s = [values[rng.randrange(len(values))] for _ in values]
        vals.append(sum(h for h, _ in s) / max(1, sum(t for _, t in s)))
    vals.sort()
    return [round(vals[int(0.025 * ba.BOOT)], 3), round(vals[int(0.975 * ba.BOOT) - 1], 3)]


def score(write: bool) -> int:
    """Score the 20 reviews against §4aq's key and apply the decision rule."""
    key, have = es.key_of("test"), done()
    rows = []
    for arm, t in chosen():
        r = have.get(t["pr"])
        lessons = set(t["lessons"])
        broken = sorted(i for i in lessons if key.get((t["pr"], i)) == "broken")
        if r is None:
            rows.append({"pr": t["pr"], "arm": arm, "reviewed": False, "broken": broken})
            continue
        ans = r["answer"]
        named = []
        for b in ans.get("breaks") or []:
            i = b.get("id") if isinstance(b, dict) else b
            if i in lessons and i not in named:
                named.append(i)
        picked = [i for i in ans.get("picked") or [] if i in lessons]
        cls = {i: key.get((t["pr"], i), "other") for i in named}
        rows.append({"pr": t["pr"], "arm": arm, "reviewed": True, "broken": broken, "picked": picked, "named": named,
                     "hits": [i for i in named if cls[i] == "broken"],
                     "false_alarms": [i for i in named if cls[i] in ("followed", "related", "other")],
                     "unsorted": [i for i in named if cls[i] == "needed_other"],
                     "picked_broken": [i for i in picked if i in broken],
                     "tokens": r["tokens"], "api_priced_usd": r["api_priced_usd"], "seconds": r["seconds"]})
    done_rows = [r for r in rows if r["reviewed"]]
    broke_rows = [r for r in done_rows if r["arm"] == "broke"]
    rng = random.Random(SEED)  # noqa: S311 - a seeded bootstrap
    reach = sum(len(r["hits"]) for r in broke_rows) / max(1, sum(len(r["broken"]) for r in broke_rows))
    fa = [len(r["false_alarms"]) for r in done_rows]
    tok = [sum(r["tokens"].values()) for r in done_rows]
    result = {"reviewed": len(done_rows), "of": len(rows),
              "reach": round(reach, 3), "reach_boot95": boot([(len(r["hits"]), len(r["broken"])) for r in broke_rows], rng),
              "broken": sum(len(r["broken"]) for r in broke_rows), "caught": sum(len(r["hits"]) for r in broke_rows),
              "picked_reach": round(sum(len(r["picked_broken"]) for r in broke_rows) / max(1, sum(len(r["broken"]) for r in broke_rows)), 3),
              "false_alarms_per_task": {"median": median(fa) if fa else None, "mean": round(mean(fa), 2) if fa else None,
                                        "clean_tasks_median": median([len(r["false_alarms"]) for r in done_rows if r["arm"] == "clean"] or [0]),
                                        "total": sum(fa)},
              "unsorted_named": sum(len(r["unsorted"]) for r in done_rows),
              "named_per_task_median": median([len(r["named"]) for r in done_rows]) if done_rows else None,
              "tokens_per_review_median": median(tok) if tok else None,
              "api_priced_usd_total": round(sum(r["api_priced_usd"] for r in done_rows), 2)}
    holds = {"reach_at_least_30": reach >= REACH_BAR,
             "median_false_alarms_at_most_1": bool(fa) and median(fa) <= FALSE_ALARM_BAR,
             "all_reviewed": len(done_rows) == len(rows)}
    holds["on_by_default"] = all(holds.values())
    out = {"section": "4au", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "status": "model-judged key (§4aq), not audited (#394); one repository (#413)",
           "okl_commit": rl.git("rev-parse", "HEAD").strip(), "prompt": PROMPT_SHA, "script_sha256": ba.sha256(Path(__file__)),
           "result": result, "holds": holds, "per_task": rows}
    print(json.dumps({k: out[k] for k in ("prompt", "result", "holds")}, indent=1))
    if write:
        dest = rl.REPO / "evals" / "results" / f"default-read-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(rl.REPO)}")
    return 0


def main() -> int:
    """run or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["run", "score"])
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return run() if a.step == "run" else score(a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
