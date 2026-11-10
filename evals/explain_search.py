#!/usr/bin/env python3
"""REPORT §4at: once a change is written, does an explanation of what its code does find the lessons it broke?

Three queries through one search, on each task's lessons as they stood when it was frozen:
T the task's words, C the added code, E Sonnet's explanation of the change (one mechanism a
sentence, written in an empty directory from the diff alone). §4al's tasks are the development
half, §4aq's the test half; the test half refuses to run until the prompt's hash is frozen.

    python3 evals/explain_search.py explain --half dev|test
    python3 evals/explain_search.py score --half dev|test [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import lesson_review as lr
import realwork_label as rl
import realwork_reach as rr
import review_action as ra
import review_repo as rp
import review_state_detail as rsd

EXPLAIN_PROMPT = """The file CHANGE.diff in your working directory is one code change, as a unified diff. Read all of it.

Say what the changed code does, one mechanism per sentence, in plain words:
- what it calls, and from where;
- what it reads and writes: files, databases, environment variables, the network, output streams;
- what it assumes about its inputs and its environment;
- how it fails, and what it returns or prints when it does;
- what its tests check, and with what data (real, recorded, or written by hand);
- what the documentation it changes now claims.
Name the functions, files, commands and settings involved. Describe; do not judge the change or suggest changes.

Answer with a JSON array of at most 25 strings, one sentence each, and nothing after it."""
PROMPT_SHA = hashlib.sha256(EXPLAIN_PROMPT.encode()).hexdigest()[:16]
FROZEN_PROMPT: str | None = None   # set by the amendment that freezes the prompt, before any test-half call
SONNET = ["claude", "-p", "--model", "sonnet", "--output-format", "json", "--restricted", "--strict-mcp-config",
          "--tools", "Read,Grep,Glob"]
ENV = {**rp.ENV}
K, K_ALSO, CODE_CUT, WORKERS, TIMEOUT, STOP_AFTER_EMPTY = 5, 10, 4000, 3, 900, 12
EXPLAINED = lr.PRIVATE / "explain-4at.jsonl"
BROKEN = "not_followed"   # §4ao's sort used check for what the diff alone could not show, so it is not counted


def tasks_of(half: str) -> list[dict]:
    """§4al's tasks for the development half, §4aq's for the test half."""
    path = rr.TASKS if half == "dev" else rp.W.tasks
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def key_of(half: str) -> dict[tuple[int, str], str]:
    """Each pair's class: broken (needed and not followed), followed, needed_other (sorted check or
    unclear), related, or other. §4al's tasks were sorted by two keys, §4ap's for half of them and
    §4ao's sort for the other half; a key holds only the pairs it judged needed."""
    if half == "dev":
        labels = {}
        for line in rr.LABELS.read_text().splitlines():
            r = json.loads(line)
            if r.get("verdict"):
                labels[(r["pr"], r["lesson"])] = r["verdict"]
        states = {k: v.get("state") for k, v in {**rsd.load(rsd.ANSWERS), **rsd.load(ra.KEY)}.items()}
        needed = set(states)
    else:
        labels = {k: v.get("verdict") for k, v in rp.keyed(rp.LABELS).items()}
        states = {k: v.get("state") for k, v in rp.keyed(rp.STATES).items()}
        needed = {k for k, v in labels.items() if v == "needed"}
    out: dict[tuple[int, str], str] = {}
    for k in set(labels) | needed:
        if k in needed:
            out[k] = "broken" if states.get(k) == BROKEN else "followed" if states.get(k) == "followed" else "needed_other"
        else:
            out[k] = "related" if labels.get(k) == "related" else "other"
    return out


def store_for(half: str, task: dict, room: Path) -> Path:
    """The task's lessons as they stood when it was frozen, from its own half's snapshot."""
    return rr.store_as_of(task, room, snapshot=rr.SNAPSHOT if half == "dev" else rp.W.store)


def ranked(db: Path, text: str, lessons: set[str], k: int) -> list[str]:
    """The first k of the task's lessons for `text`: the full-text search fused with potion, linear (§4am's R)."""
    from okl import core
    from okl.store import Store
    if not text.strip():
        return []
    ids = [n.id for n in core.ranked_candidates(Store(f"sqlite:///{db}"), text, 1000, "linear").nodes]
    return [i for i in ids if i in lessons][:k]


def task_words(task: dict) -> str:
    """T: the title and issues, as a briefing before the code sees them."""
    return " ".join([task["title"], *(f"{i['title']} {i['body']}" for i in task["issues"])]).strip()


def added_code(task: dict) -> str:
    """C: the change's added lines, whitespace collapsed, cut to CODE_CUT characters."""
    lines = [line[1:] for line in ra.whole(task).splitlines() if line.startswith("+") and not line.startswith("+++")]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()[:CODE_CUT]


def explained() -> dict[tuple[str, int, str], list[str]]:
    """Every explanation kept, by half, PR and prompt hash."""
    if not EXPLAINED.exists():
        return {}
    return {(r["half"], r["pr"], r["prompt"]): r["sentences"] for r in map(json.loads, EXPLAINED.read_text().splitlines()) if r.get("sentences")}


def sentences_in(text: str) -> list[str]:
    """The largest JSON array of strings in `text`, so a short list quoted inside a sentence never
    wins. realwork_label.last_array reads arrays of objects only, and returned nothing for every
    explanation of the first pass."""
    decoder, found = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, list) and obj and all(isinstance(x, str) for x in obj) and (found is None or len(obj) >= len(found)):
            found = obj
    return [s.strip() for s in found or [] if s.strip()]


def explain_one(half: str, task: dict) -> dict | None:
    """One Sonnet call: the change's explanation, from the diff alone, in an empty directory."""
    with tempfile.TemporaryDirectory(prefix="okl-4at-") as room:
        (Path(room) / "CHANGE.diff").write_text(ra.whole(task))
        try:
            p = subprocess.run(SONNET, input=EXPLAIN_PROMPT, capture_output=True, text=True, timeout=TIMEOUT, cwd=room, env=ENV)
        except subprocess.TimeoutExpired:
            return None
    try:
        result = json.loads(p.stdout).get("result") or ""
    except ValueError:
        result = p.stdout
    sentences = sentences_in(result)
    return {"half": half, "pr": task["pr"], "prompt": PROMPT_SHA, "sentences": sentences} if sentences else None


def explain(half: str) -> int:
    """Explain every task of the half that has no explanation under this prompt; stop at a usage limit."""
    if half == "test" and FROZEN_PROMPT != PROMPT_SHA:
        sys.exit(f"the test half needs the prompt frozen first: FROZEN_PROMPT is {FROZEN_PROMPT}, the prompt is {PROMPT_SHA}")
    have = explained()
    todo = [t for t in tasks_of(half) if (half, t["pr"], PROMPT_SHA) not in have]
    print(f"{half}: {len(todo)} to explain with prompt {PROMPT_SHA}", file=sys.stderr, flush=True)
    empty = 0
    EXPLAINED.parent.mkdir(parents=True, exist_ok=True)
    with EXPLAINED.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(explain_one, half, t) for t in todo]
        for n, f in enumerate(as_completed(futures), 1):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n")
                sink.flush()
                empty = 0
            else:
                empty += 1
                if empty >= STOP_AFTER_EMPTY:
                    for w in futures:
                        w.cancel()
                    sys.exit(f"{empty} calls in a row returned nothing, which is what a usage limit looks like; rerun to resume")
            if n % 10 == 0:
                print(f"  {n}/{len(todo)}", file=sys.stderr, flush=True)
    missing = sum(1 for t in tasks_of(half) if (half, t["pr"], PROMPT_SHA) not in explained())
    print(json.dumps({"half": half, "prompt": PROMPT_SHA, "missing": missing}))
    return 0 if not missing else 2


def reach_rows(half: str) -> list[dict]:
    """Each task's broken lessons and each query's first K_ALSO."""
    key, have = key_of(half), explained()
    rows = []
    with tempfile.TemporaryDirectory(prefix="okl-4at-rank-") as room:
        for t in tasks_of(half):
            lessons = set(t["lessons"])
            db = store_for(half, t, Path(room))
            e = " ".join(have.get((half, t["pr"], PROMPT_SHA), []))
            rows.append({"pr": t["pr"], "broken": sorted(i for i in lessons if key.get((t["pr"], i)) == "broken"),
                         "explained": bool(e),
                         "top": {"T": ranked(db, task_words(t), lessons, K_ALSO), "C": ranked(db, added_code(t), lessons, K_ALSO),
                                 "E": ranked(db, e, lessons, K_ALSO)}})
            db.unlink(missing_ok=True)
    return rows


def reach(rows: list[dict], arm: str, k: int) -> float:
    """The share of the broken lessons that the arm's first k name."""
    hits = sum(len(set(r["broken"]) & set(r["top"][arm][:k])) for r in rows)
    return round(hits / max(1, sum(len(r["broken"]) for r in rows)), 3)


def boot_reach(rows: list[dict], arm: str, k: int, rng: random.Random) -> list[float]:
    """The reach's bootstrap interval over tasks with a broken lesson."""
    with_b = [r for r in rows if r["broken"]]
    vals = sorted(reach([with_b[rng.randrange(len(with_b))] for _ in with_b], arm, k) for _ in range(ba.BOOT))
    return [vals[int(0.025 * ba.BOOT)], vals[int(0.975 * ba.BOOT) - 1]]


def boot_gain(rows: list[dict], a: str, b: str, k: int, rng: random.Random) -> list[float]:
    """The paired gain of arm a over arm b, bootstrapped over tasks with a broken lesson."""
    with_b = [r for r in rows if r["broken"]]
    vals = []
    for _ in range(ba.BOOT):
        s = [with_b[rng.randrange(len(with_b))] for _ in with_b]
        vals.append(reach(s, a, k) - reach(s, b, k))
    vals.sort()
    return [round(vals[int(0.025 * ba.BOOT)], 3), round(vals[int(0.975 * ba.BOOT) - 1], 3)]


def score(half: str, write: bool) -> int:
    """Score the half; write a receipt with `write`."""
    rows, key = reach_rows(half), key_of(half)
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    with_b = [r for r in rows if r["broken"]]
    held = {arm: {c: sum(1 for r in rows for i in r["top"][arm][:K] if key.get((r["pr"], i), "other") == c)
                  for c in ("broken", "followed", "needed_other", "related", "other")} for arm in ("T", "C", "E")}
    result = {"tasks": len(rows), "tasks_with_broken": len(with_b), "broken": sum(len(r["broken"]) for r in rows),
              "explained": sum(1 for r in rows if r["explained"]),
              "reach": {f"{arm}@{k}": reach(rows, arm, k) for arm in ("T", "C", "E") for k in (K, K_ALSO)},
              "reach_boot95": {f"E@{K}": boot_reach(rows, "E", K, rng)},
              "gain": {"E-T@5": boot_gain(rows, "E", "T", K, rng), "E-C@5": boot_gain(rows, "E", "C", K, rng)},
              "first_k_holds": held,
              "tasks_with_broken_none_in_E@5": sum(1 for r in with_b if not set(r["broken"]) & set(r["top"]["E"][:K]))}
    holds = {"gain_over_T_lower_bound_above_zero": result["gain"]["E-T@5"][0] > 0, "reach_at_5_at_least_50": result["reach"][f"E@{K}"] >= 0.5}
    out = {"section": "4at", "half": half, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "status": "development half: in-sample, not a result" if half == "dev" else "model-judged key, not yet audited (#394)",
           "okl_commit": rl.git("rev-parse", "HEAD").strip(), "prompt": PROMPT_SHA, "script_sha256": ba.sha256(Path(__file__)),
           "result": result, "holds": {**holds, "all": all(holds.values())} if half == "test" else None,
           "per_task": rows}
    print(json.dumps({k: out[k] for k in ("half", "status", "prompt", "result", "holds")}, indent=1))
    if write:
        dest = rr.REPO / "evals" / "results" / f"explain-search-{half}-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(rr.REPO)}")
    return 0


def main() -> int:
    """explain or score one half."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["explain", "score"])
    ap.add_argument("--half", choices=["dev", "test"], required=True)
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return explain(a.half) if a.step == "explain" else score(a.half, a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
