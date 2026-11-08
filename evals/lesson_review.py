#!/usr/bin/env python3
"""REPORT §4ao: a review of every lesson against a pull request's diff, on §4am's test half.

`run` asks Sonnet (never Opus, the judge), twenty lessons a call with no tools, whether each lesson
bears on the frozen change. Answers land in evals/bench/private/realwork/ as each call returns, so a
rerun asks only for what is missing. `run --pilot` makes one call on a development-half task, to check
the plumbing, and keeps nothing. `score` reads the answers against §4al's labels and writes the receipt.

    python3 evals/lesson_review.py run [--pilot]
    python3 evals/lesson_review.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import realwork_label as rl
import realwork_reach as rr

REPO = rr.REPO
PRIVATE = REPO / "evals" / "bench" / "private" / "realwork"
ANSWERS = PRIVATE / "review-answers.jsonl"
USAGE = PRIVATE / "review-usage.jsonl"
LEDGER = REPO / "evals" / "missed_lessons.jsonl"
ARMS_RECEIPT = REPO / "evals" / "results" / "briefing-arms-20261108-1716.json"
TRIGGERS_RECEIPT = REPO / "evals" / "results" / "path-triggers-20261108-1720.json"
MODEL = "sonnet"
REVIEWER = ["claude", "-p", "--model", MODEL, "--restricted", "--strict-mcp-config", "--output-format", "json",
            "--tools", ""]
ROUNDS, WORKERS, TIMEOUT, LINE_CUT, LEDGER_PR = 3, 3, 600, 200, 388
REACH_BAR, WRONG_BAR, BEST_BRIEFING = 0.70, 5, 0.824   # BEST_BRIEFING: §4am's three arms together, test half

PROMPT = """You are reviewing a pull request against what a team has learned the hard way and written down so it is not repeated.

PULL REQUEST: {title}

WHAT IT WAS FOR:
{issues}

THE DIFF:
{change}

WHAT THE TEAM HAS WRITTEN DOWN:
{lessons}

For each item above, ask one question: because of this item, should the author of this pull request do something differently, or check something before merging? Flag an item only if you can point to the line of the diff it bears on. An item on a similar subject that changes nothing here is not flagged, and an item can bear on the diff without sharing a word with it.

Reply with one JSON array and nothing else, holding one object for every item, each exactly once: [{{"id": "<the id in square brackets>", "flag": true or false, "line": "<the line of the diff it bears on; empty when not flagged>"}}]"""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
_lock = threading.Lock()


def load_tasks() -> tuple[list[dict], list[dict]]:
    """(development, test), as §4am split them."""
    return ba.halves([json.loads(line) for line in rr.TASKS.read_text().splitlines() if line.strip()])


def change_of(task: dict) -> str:
    """The task's frozen change, built and cut as the judge's was."""
    diff = rl.git("diff", f"{task['base']}..{task['commit']}")
    return diff if len(diff) <= rl.CUT else diff[:rl.CUT] + f"\n[... cut: {len(diff) - rl.CUT} more characters]"


def ask(prompt: str, room: Path) -> tuple[list | None, dict]:
    """The reviewer's array for `prompt` (None when it gave none) and what the call cost."""
    start = time.monotonic()
    try:
        p = subprocess.run(REVIEWER, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=room)
    except subprocess.TimeoutExpired:
        return None, {"seconds": TIMEOUT, "error": "timeout"}
    use: dict = {"seconds": round(time.monotonic() - start, 1)}
    try:
        reply = json.loads(p.stdout)
    except ValueError:
        return rl.last_array(p.stdout), {**use, "error": "not json"}
    u = reply.get("usage") or {}
    use.update({"input": u.get("input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0), "output": u.get("output_tokens", 0),
                "api_priced_usd": reply.get("total_cost_usd", 0)})
    return rl.last_array(reply.get("result") or ""), use


def resolve(given: str, ids: list[str]) -> str | None:
    """The lesson in this call that `given` names: as written, or the one id that ends with it.
    The reviewer can shorten a seed lesson's id (§4ao's amendments). An id that could mean two
    lessons names neither, and no answer can reach a lesson outside its own call."""
    if given in ids:
        return given
    hits = [i for i in ids if i.endswith(f":{given}")]
    return hits[0] if len(hits) == 1 else None


def one(task: dict, ids: list[str], change: str, texts: dict[str, str], room: Path) -> tuple[list[dict], dict]:
    """One call: the answers it gave for `ids`, and its cost."""
    issues = "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in task["issues"]) or "(none)"
    prompt = PROMPT.format(title=task["title"], issues=issues, change=change, lessons="\n\n".join(texts[i] for i in ids))
    got, use = ask(prompt, room)
    wanted, rows = set(ids), []
    for item in got or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("flag"), bool):
            continue
        lesson = resolve(item["id"], ids)
        if lesson in wanted:
            wanted.discard(lesson)
            rows.append({"pr": task["pr"], "lesson": lesson, "flag": item["flag"], "line": str(item.get("line") or "")[:LINE_CUT],
                         "model": MODEL, "prompt": PROMPT_SHA})
    return rows, {"pr": task["pr"], "asked": len(ids), "answered": len(rows), "prompt": PROMPT_SHA, **use}


def load_answers() -> dict[tuple[int, str], dict]:
    """The answers kept so far under this prompt."""
    out: dict[tuple[int, str], dict] = {}
    if ANSWERS.exists():
        for line in ANSWERS.read_text().splitlines():
            r = json.loads(line)
            if r.get("prompt") == PROMPT_SHA:
                out[(r["pr"], r["lesson"])] = r
    return out


def run(pilot: bool) -> int:
    """Ask for every pair not yet answered (or make the pilot's one call)."""
    dev, test = load_tasks()
    texts = rl.lesson_text(rr.SNAPSHOT)
    with tempfile.TemporaryDirectory(prefix="okl-4ao-") as tmp:
        room = Path(tmp)   # the reviewer runs outside the repository, with no tools
        if pilot:
            t = dev[0]
            ids = [i for i in sorted(t["lessons"]) if i in texts][:rl.BATCH]
            rows, use = one(t, ids, change_of(t), texts, room)
            print(json.dumps({"pilot_on": t["pr"], "cost": use, "flag_is_bool": all(isinstance(r["flag"], bool) for r in rows)}, indent=1))
            return 0 if use["answered"] == use["asked"] else 2
        done = load_answers()
        changes = {t["pr"]: change_of(t) for t in test}
        with ANSWERS.open("a") as answers, USAGE.open("a") as usage, ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for attempt in range(ROUNDS):
                jobs = []
                for t in test:
                    todo = [i for i in sorted(t["lessons"]) if (t["pr"], i) not in done and i in texts]
                    jobs += [(t, todo[k:k + rl.BATCH]) for k in range(0, len(todo), rl.BATCH)]
                if not jobs:
                    break
                print(f"round {attempt + 1}: {len(jobs)} calls · {MODEL} prompt {PROMPT_SHA}", file=sys.stderr)
                futures = [pool.submit(one, t, ids, changes[t["pr"]], texts, room) for t, ids in jobs]
                for n, future in enumerate(as_completed(futures), 1):
                    rows, use = future.result()
                    with _lock:
                        for r in rows:
                            done[(r["pr"], r["lesson"])] = r
                            answers.write(json.dumps(r, ensure_ascii=False) + "\n")
                        usage.write(json.dumps(use) + "\n")
                        answers.flush()
                        usage.flush()
                    if n % 25 == 0:
                        print(f"  {n}/{len(jobs)} calls", file=sys.stderr)
    missing = sum(1 for t in test for i in t["lessons"] if (t["pr"], i) not in done)
    print(json.dumps({"tasks": len(test), "answered": len(done), "missing": missing, "prompt": PROMPT_SHA}))
    return 0 if not missing else 2


def score(write: bool) -> int:
    """Score the answers against §4al's labels; write the receipt with `write`."""
    _, test = load_tasks()
    labels: dict[tuple[int, str], str] = {}
    for line in rr.LABELS.read_text().splitlines():
        r = json.loads(line)
        if r.get("verdict"):
            labels[(r["pr"], r["lesson"])] = r["verdict"]
    answers = load_answers()
    missing = sorted(f"#{t['pr']} {i}" for t in test for i in t["lessons"] if (t["pr"], i) not in answers)
    rows, per_task = [], []
    for t in test:
        needed = sorted(i for i in t["lessons"] if labels.get((t["pr"], i)) == "needed")
        flagged = sorted(i for i in t["lessons"] if answers.get((t["pr"], i), {}).get("flag"))
        rows.append({"pr": t["pr"], "half": "test", "needed": needed, "named": {"base": [], "review": flagged}})
        per_task.append({"pr": t["pr"], "needed": needed, "flagged": flagged, "missed": sorted(set(needed) - set(flagged)),
                         "lines": {i: answers[(t["pr"], i)]["line"] for i in flagged}})
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    v = ba.tally(rows, "review", labels, rng)   # with an empty base, the gain is the reach and its interval the reach's
    verdicts: dict[str, int] = {}
    for r in rows:
        for i in r["named"]["review"]:
            verdict = labels.get((r["pr"], i)) or "unlabelled"
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
    wrong = [sum(1 for i in r["named"]["review"] if labels.get((r["pr"], i)) == "no") for r in rows]
    flagged_n = [len(r["named"]["review"]) for r in rows]
    ledger = [json.loads(line)["lesson"] for line in LEDGER.read_text().splitlines() if line.strip()]
    on_388 = next(r for r in rows if r["pr"] == LEDGER_PR)
    ledger_flagged = {i: i in on_388["named"]["review"] for i in ledger}
    arms = {r["pr"]: set(r["named"]["all"]) for r in json.loads(ARMS_RECEIPT.read_text())["per_task"]}
    trig = {r["pr"]: set(r["named"]["P"]) for r in json.loads(TRIGGERS_RECEIPT.read_text())["per_task"]}
    kept, needed_total, read = 0, 0, []
    for t, r in zip(test, rows, strict=True):
        cand = (arms[t["pr"]] | trig[t["pr"]]) & set(t["lessons"])
        read.append(len(cand))
        kept += len(set(r["needed"]) & set(r["named"]["review"]) & cand)
        needed_total += len(r["needed"])
    use = [json.loads(line) for line in USAGE.read_text().splitlines()] if USAGE.exists() else []
    use = [u for u in use if u.get("prompt") == PROMPT_SHA]
    by_pr: dict[int, dict] = {}
    for u in use:
        p = by_pr.setdefault(u["pr"], {"calls": 0, "tokens": 0, "seconds": 0.0, "usd": 0.0})
        p["calls"] += 1
        p["tokens"] += u.get("input", 0) + u.get("cache_read", 0) + u.get("cache_write", 0) + u.get("output", 0)
        p["seconds"] += u.get("seconds", 0)
        p["usd"] += u.get("api_priced_usd", 0) or 0
    cost = {"calls": len(use), "unanswered_calls": sum(1 for u in use if u.get("answered", 0) < u.get("asked", 0))}
    if by_pr:
        cost |= {f"per_pr_median_{k}": round(statistics.median(p[k] for p in by_pr.values()), 2) for k in ("calls", "tokens", "seconds", "usd")}
        cost["total_api_priced_usd"] = round(sum(p["usd"] for p in by_pr.values()), 2)
    lower, wrong_median = v["gain_boot95"][0], statistics.median(wrong)
    holds = {"reach_lower_bound_at_least_70": lower >= REACH_BAR, "named_wrongly_median_at_most_5": wrong_median <= WRONG_BAR,
             "both_ledger_lessons_flagged": all(ledger_flagged.values())}
    predictions = {"reach above the best briefing's 82.4%": v["reach"] > BEST_BRIEFING,
                   "flags both ledger lessons": all(ledger_flagged.values()),
                   "misses a needed lesson on more than a third of the tasks": v["failure_rate"] > 1 / 3,
                   "named wrongly at most 5 at the median task": wrong_median <= WRONG_BAR}
    usable = not missing
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    out = {"section": "4ao", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": head,
           "status": "model-judged, not yet audited (#394)" if usable else f"INCOMPLETE: {len(missing)} pair(s) unanswered",
           "usable": usable, "reviewer": {"model": MODEL, "prompt": PROMPT_SHA}, "missing": missing[:50],
           "inputs": {"labels_sha256": ba.sha256(rr.LABELS), "tasks_sha256": ba.sha256(rr.TASKS), "store_sha256": ba.sha256(rr.SNAPSHOT)},
           "result": {"tasks": v["tasks"], "tasks_with_needed": v["tasks_with_needed"], "needed": v["needed"], "reach": v["reach"],
                      "reach_boot95": v["gain_boot95"], "tasks_missing": v["tasks_missing"], "failure_rate": v["failure_rate"],
                      "failure_wilson95": v["failure_wilson95"], "flagged_median": statistics.median(flagged_n), "flagged_max": max(flagged_n),
                      "flagged_by_label": verdicts, "named_wrongly_median": wrong_median, "named_wrongly_max": max(wrong)},
           "ledger": ledger_flagged, "cost": cost,
           "secondary_estimate": {"note": "if the review read only the lessons §4am's three arms or §4an's P name",
                                  "reach_kept": round(kept / max(1, needed_total), 3), "lessons_read_median": statistics.median(read),
                                  "lessons_read_full_median": statistics.median(len(t["lessons"]) for t in test)},
           "holds": {**holds, "all": all(holds.values())}, "predictions": predictions, "per_task": per_task}
    print(out["status"])
    print(json.dumps({k: out[k] for k in ("result", "ledger", "cost", "secondary_estimate", "holds", "predictions")}, indent=1))
    if write:
        path = REPO / "evals" / "results" / f"lesson-review-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(REPO)}")
    return 0 if usable else 2


def main() -> int:
    """Dispatch `run` or `score`."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").add_argument("--pilot", action="store_true")
    sub.add_parser("score").add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    return run(args.pilot) if args.cmd == "run" else score(args.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
