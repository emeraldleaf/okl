#!/usr/bin/env python3
"""REPORT §4bb: does a line saying when a lesson applies, by mechanism, help a picker find it?

§4ba's picker found the right lesson about half the time from a plan or a diff. On #196 it saw the
faulty line and missed a lesson written about "audits" for code that was an eval script: lessons
are named after the incident that taught them. A separate model, shown only each lesson's text,
writes one line saying when it applies by what the code does. The picks of §4ba are re-run on the
same task words, the same plans and the same diffs, with and without those lines, in one sitting.

    python3 evals/when_lines.py write      # the lines, from the lessons alone; then freeze by hash
    python3 evals/when_lines.py run
    python3 evals/when_lines.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import default_read as dr
import explain_search as es
import outcome_replay as o
import plan_reach as pr
import run_guard

LINES = o.REPO / "evals" / "when-lines-4bb.json"
PLANS = o.REPO / "evals" / "results" / "plan-reach-20261111-1435.json"   # §4ba's committed plans, by name: a glob would take an uncommitted receipt
OUT = o.REPO / "evals" / "bench" / "private" / "realwork" / "when-lines-4bb.jsonl"
ARMS = tuple(f"{start}_{lines}" for start in pr.ARMS for lines in ("plain", "when"))
BATCH, GAIN, MIN_COMPLETE = 20, 0.15, 135
FROZEN_LINES: str | None = "428b12d45bd7256c"   # frozen 2026-11-11, after the lines were written and before any pick
WRITE_PROMPT = """Below are lessons a software team keeps, each as its id and full text.

For each, write one line saying when it applies: by what the code or the change does (a mechanism, such as reading files from a folder, resolving where data is stored, building a shell command, comparing a run with earlier runs, retrying a network call), not by the incident that taught it, and not only in the lesson's own words. A developer reading the line while writing code should recognise that the lesson bears on it. At most 25 words each.

Answer with one JSON object mapping each id to its line, and nothing after it.

{lessons}"""


def lesson_texts() -> dict[str, str]:
    """Every lesson any of the five tasks could see, with its full text as it stood."""
    texts: dict[str, str] = {}
    for t in o.tasks():
        frozen = {x["pr"]: x for x in es.tasks_of(pr.HALF[t["set"]])}[t["pr"]]
        listed = {line.split(" | ", 1)[0] for line in es.lesson_lines(pr.HALF[t["set"]], frozen)}
        with tempfile.TemporaryDirectory() as side:
            full = dr.full_text(es.store_for(pr.HALF[t["set"]], frozen, Path(side)))
        for i in listed:
            texts.setdefault(i, full.get(i, ""))
    return texts


def last_object(text: str) -> dict | None:
    """The last JSON object of strings in a reply."""
    decoder, found = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj and all(isinstance(v, str) for v in obj.values()):
                found = obj
    return found


def own_id(key: str, ids: list[str]) -> str | None:
    """The id a model's key means, within this batch: as written, or the one id that ends with it.
    A model echoing ids can drop a prefix (lesson model-echoed-ids-get-shortened); an ambiguous key
    is left unanswered."""
    if key in ids:
        return key
    ends = [i for i in ids if i.endswith(f":{key}") or i.endswith(key)]
    return ends[0] if len(ends) == 1 else None


def write() -> int:
    """Write a line for every lesson, from the lessons' text alone, in batches."""
    texts = lesson_texts()
    have = json.loads(LINES.read_text()) if LINES.exists() else {}
    todo = sorted(i for i in texts if i not in have)
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    print(f"{len(todo)} lessons in {len(batches)} batches", file=sys.stderr, flush=True)

    def one(ids: list[str]) -> dict:
        body = "\n\n".join(f"[{i}]\n{texts[i].strip()}" for i in ids)
        got = last_object(pr.ask([*pr.SONNET, "--tools", ""], WRITE_PROMPT.format(lessons=body)) or "") or {}
        return {i: " ".join(got[k].split()) for k in got if (i := own_id(k, ids))}

    with ThreadPoolExecutor(max_workers=o.WORKERS) as pool:
        for got in pool.map(one, batches):
            have.update(got)
    LINES.write_text(json.dumps(dict(sorted(have.items())), indent=1, ensure_ascii=False) + "\n")
    missing = sorted(set(texts) - set(have))
    print(f"wrote {len(have)} lines; missing {len(missing)}", file=sys.stderr)
    return 0 if not missing else 2


def calls() -> list[dict]:
    """Every pick, in a seeded order."""
    out = [{"pr": t["pr"], "arm": a, "rep": r} for t in o.tasks() for a in ARMS for r in range(o.REPEATS)]
    random.Random(o.SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def kept() -> dict[tuple, dict]:
    """Every pick kept under these lines."""
    if not OUT.exists():
        return {}
    return {o.ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if r.get("lines") == o.sha(LINES)}


def pick(call: dict, task: dict, plans: dict[tuple, list[str]]) -> dict | None:
    """One pick of ten, from the same starting point §4ba used, with or without the lines."""
    start, how = call["arm"].rsplit("_", 1)
    frozen = {x["pr"]: x for x in es.tasks_of(pr.HALF[task["set"]])}[task["pr"]]
    if start == "plan":
        plan = plans.get((task["pr"], call["rep"]))
        if not plan:
            return None
        change = "\n".join(f"- {s}" for s in plan)
    elif start == "diff":
        change = o.git("diff", task["base"], task["frozen"])[:pr.DIFF_CUT]
    else:
        change = o.task_words(task)
    lines = es.lesson_lines(pr.HALF[task["set"]], frozen)
    if how == "when":
        when = json.loads(LINES.read_text())
        lines = [f"{line} — applies when: {when.get(line.split(' | ', 1)[0], '')}" for line in lines]
    text = pr.ask([*pr.SONNET, "--tools", ""], pr.PICK_PROMPT.format(kind=pr.KIND[start], k=pr.K, change=change, lessons="\n".join(lines)))
    picked = pr.last_array(text or "")
    if not picked:
        return None
    known = {line.split(" | ", 1)[0] for line in lines}
    picked = [i for i in picked if i in known][:pr.K]
    return {**call, "lines": o.sha(LINES), "picked": picked, "hit": task["lesson"] in picked,
            "rank": picked.index(task["lesson"]) + 1 if task["lesson"] in picked else None}


def run() -> int:
    """Make every pick without a result yet; stops when calls keep failing (a usage limit)."""
    have_lines = o.sha(LINES) if LINES.exists() else "none written"
    if have_lines != FROZEN_LINES:
        print(f"refused: the lines ({have_lines}) are not frozen; FROZEN_LINES is {FROZEN_LINES}", file=sys.stderr)
        return 2
    plans = {(r["pr"], r["rep"]): r["plan"] for r in json.loads(PLANS.read_text())["rows"] if r["arm"] == "plan" and r.get("plan")}
    by_pr, have = {t["pr"]: t for t in o.tasks()}, kept()
    todo = [c for c in calls() if o.ident(c) not in have]
    print(f"{len(todo)} of {len(calls())} picks to make", file=sys.stderr, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=o.WORKERS) as pool:
        futures = {pool.submit(pick, c, by_pr[c["pr"]], plans): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= o.STOP_AFTER_EMPTY:
                print(f"stopped: {empty} picks in a row gave no result", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def reading(rate: dict[str, float], complete: bool) -> str:
    """The lines help if, from a plan and from a diff, they raise the hit rate by GAIN on average."""
    if not complete:
        return "not complete"
    gain = round(mean(rate[f"{s}_when"] - rate[f"{s}_plain"] for s in ("plan", "diff")), 3)
    return "the lines help" if gain >= GAIN else "the lines do not help enough"


def score(write: bool) -> int:
    """Hit rates per arm, averaged over tasks, and the stated reading."""
    guard = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in o.tasks()]
    per_task = {a: {p: round(mean(r["hit"] for r in rows if r["arm"] == a and r["pr"] == p), 3) for p in prs
                    if any(r["arm"] == a and r["pr"] == p for r in rows)} for a in ARMS}
    rate = {a: round(mean(per_task[a].values()), 3) if per_task[a] else 0.0 for a in ARMS}
    out = {"section": "4bb", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "lines": o.sha(LINES), "picks": len(rows), "of": len(calls()),
           "hit_rate": rate, "per_task": per_task, "reading": reading(rate, len(rows) >= MIN_COMPLETE),
           "gain": {s: round(rate[f"{s}_when"] - rate[f"{s}_plain"], 3) for s in pr.ARMS},
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "arm", "rep", "hit", "rank", "picked")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"when-lines-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(o.REPO)}")
    return 0 if len(rows) == len(calls()) else 2


def main() -> int:
    """write, run or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["write", "run", "score"])
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return {"write": write, "run": run}.get(a.step, lambda: score(a.receipt))()


if __name__ == "__main__":
    raise SystemExit(main())
