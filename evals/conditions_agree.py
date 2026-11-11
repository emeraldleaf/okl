#!/usr/bin/env python3
"""REPORT §4av: do yes/no conditions make two models agree on whether a change broke a lesson?

The 20 lessons that hold 65% of past breaks (break-concentration-20261110-1600.json) each get two to
four yes/no questions and a line saying when the lesson is in scope and when it is not
(evals/conditions-4av.json, written from the development half's cases only). Two models that wrote
neither the lessons nor the conditions, Sonnet and Fable, each judge every case twice: with the
lesson as `okl show` gives it (arm A) and with the conditions after it (arm B). The prompt is §4au's
follow-up prompt, unchanged.

    python3 evals/conditions_agree.py pilot              # development half, arm B: find misread wording
    python3 evals/conditions_agree.py run                # test half, both arms; refuses until frozen
    python3 evals/conditions_agree.py score --half dev|test [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import default_read as dr
import explain_search as es
import lesson_review as lr
import realwork_label as rl
import review_action as ra
import review_repo as rp
import run_guard

CONDITIONS = rl.REPO / "evals" / "conditions-4av.json"
CONCENTRATION = rl.REPO / "evals" / "results" / "break-concentration-20261110-1600.json"
PROMPT = dr.SETTLE_PROMPT   # §4au's follow-up prompt, so arm A is the call that follow-up made
assert dr.SETTLE_SHA == "7b2f46b1d66ab41b", "the §4au follow-up prompt changed"
JUDGES = {"sonnet": ["claude", "-p", "--model", "sonnet", *rp.READ_ONLY],
          "fable": ["claude", "-p", "--model", "fable", *rp.READ_ONLY]}
FROZEN_CONDITIONS: str | None = "5b30c4808857b727"   # frozen by §4av's amendment of 2026-11-10, after the pilot
OUT = lr.PRIVATE / "conditions-4av.jsonl"
UNREAD = lr.PRIVATE / "conditions-4av-unread.jsonl"
SEED, RELATED, WORKERS, TIMEOUT, STOP_AFTER_EMPTY = 4, 15, 4, 1500, 8
KAPPA_GAIN, KEEP_FLAGGED, EXTRA_ALARMS, MIN_COMPLETE = 0.15, 2 / 3, 2, 60


def conditions_sha() -> str:
    """The conditions file's hash, which every arm-B verdict carries."""
    return hashlib.sha256(CONDITIONS.read_bytes()).hexdigest()[:16]


def lessons() -> list[str]:
    """The 20 most-broken lessons, most broken first."""
    return [r["lesson"] for r in json.loads(CONCENTRATION.read_text())["top20"]]


def block(lesson: str) -> str:
    """Arm B's addition: the conditions as the lesson would carry them."""
    c = json.loads(CONDITIONS.read_text())[lesson]
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(c["questions"], 1))
    return ("Conditions. This change breaks the lesson when the lesson is in scope and any answer below is no.\n"
            f"In scope when {c['in_scope']}.\nNot in scope when {c['not_in_scope']}.\n{qs}\n")


def cases(half: str) -> list[dict]:
    """The test half: every pair of these lessons §4aq's key sorted broken or followed, and RELATED
    pairs it labelled related, drawn with random.Random(SEED). The development half (the pilot): the
    first broken and the first followed case of each lesson, in pull-request order."""
    top, key = set(lessons()), es.key_of(half)
    mine = sorted((pr, lesson, cls) for (pr, lesson), cls in key.items() if lesson in top)
    if half == "test":
        needed = [{"pr": p, "lesson": le, "key": c} for p, le, c in mine if c in ("broken", "followed")]
        related = [{"pr": p, "lesson": le, "key": c} for p, le, c in mine if c == "related"]
        rng = random.Random(SEED)  # noqa: S311 - a seeded draw, not a secret
        return needed + rng.sample(related, RELATED)  # NOSONAR - seeded, reproducible on purpose
    out = []
    for lesson in lessons():
        for cls in ("broken", "followed"):
            first = next(({"pr": p, "lesson": le, "key": c} for p, le, c in mine if le == lesson and c == cls), None)
            out += [first] if first else []
    return out


def calls(half: str, arms: tuple[str, ...]) -> list[dict]:
    """Every call a step makes: each case, under each arm, by each judge."""
    return [{**c, "half": half, "arm": arm, "judge": j} for c in cases(half) for arm in arms for j in JUDGES]


def ident(row: dict) -> tuple:
    """A call's identity: an arm-B verdict counts only under the conditions it was given."""
    return (row["half"], row["pr"], row["lesson"], row["arm"], row["judge"], row.get("conditions") if row["arm"] == "B" else "")


def kept() -> dict[tuple, dict]:
    """Every verdict kept under this prompt."""
    if not OUT.exists():
        return {}
    return {ident(r): r for r in map(json.loads, OUT.read_text().splitlines()) if r.get("prompt") == dr.SETTLE_SHA}


def verdict_in(text: str) -> dict | None:
    """The last JSON object in the reply that carries a verdict. Fable sometimes ends the object
    without its closing brace (5 of the pilot's 35 Fable replies); when nothing parses, one is added."""
    got, decoder = None, json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, dict) and "verdict" in obj:
                got = obj
    tail = text.rstrip()
    if got is None and tail and not tail.endswith("}"):
        return verdict_in(tail + "}")
    return got


def keep_unread(call: dict, reply: dict) -> None:
    """A paid reply with no verdict is kept, so a parsing fix can read it without calling again."""
    with UNREAD.open("a") as sink:
        sink.write(json.dumps({**call, "prompt": dr.SETTLE_SHA, "result": reply.get("result"),
                               "subtype": reply.get("subtype")}) + "\n")


def judge_one(call: dict, task: dict) -> dict | None:
    """One blind verdict: one judge, one lesson, one arm, in a copy of the repository with the change applied."""
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="okl-4av-store-") as side, rp.checkout(task) as room:
        db = es.store_for(call["half"], task, Path(side))
        lesson = dr.full_text(db).get(call["lesson"], "")
        if not lesson:
            print(f"  #{call['pr']} {call['lesson']}: not in the task's store", file=sys.stderr, flush=True)
            return None
        if call["arm"] == "B":
            lesson += block(call["lesson"])
        (room / dr.CHANGE_FILE).write_text(ra.whole(task))
        try:
            p = subprocess.run(JUDGES[call["judge"]], input=PROMPT.format(lesson=lesson), capture_output=True,
                               text=True, timeout=TIMEOUT, cwd=room, env=rp.ENV)
        except subprocess.TimeoutExpired:
            print(f"  #{call['pr']} {call['lesson']} {call['arm']}/{call['judge']}: timed out", file=sys.stderr, flush=True)
            return None
    try:
        reply = json.loads(p.stdout)
    except ValueError:
        print(f"  #{call['pr']} {call['lesson']} {call['arm']}/{call['judge']}: unreadable reply, exit {p.returncode}: "
              f"{(p.stderr or p.stdout)[-200:]!r}", file=sys.stderr, flush=True)
        return None
    models = list(reply.get("modelUsage") or {})
    if not any(call["judge"] in m for m in models):   # lesson n_473aec369b25: a verdict from another grader is refused
        print(f"  #{call['pr']} {call['lesson']}: judge {call['judge']} answered as {models}", file=sys.stderr, flush=True)
        return None
    got = verdict_in(reply.get("result") or "")
    if got is None or got.get("verdict") not in ("broken", "followed", "not applicable"):
        print(f"  #{call['pr']} {call['lesson']} {call['arm']}/{call['judge']}: no verdict ({reply.get('subtype')}): "
              f"{(reply.get('result') or '')[-200:]!r}", file=sys.stderr, flush=True)
        keep_unread(call, reply)
        return None
    return {**call, "prompt": dr.SETTLE_SHA, "conditions": conditions_sha() if call["arm"] == "B" else None,
            "verdict": got["verdict"], "reason": got.get("reason"), "evidence": got.get("evidence"), "model": models,
            "seconds": round(time.monotonic() - start, 1), "api_priced_usd": reply.get("total_cost_usd", 0),
            "okl_commit": rl.git("rev-parse", "HEAD").strip()}


def run(half: str, arms: tuple[str, ...]) -> int:
    """Make every call without a verdict yet; resumable, and stops when calls keep failing (a usage limit)."""
    if half == "test" and conditions_sha() != FROZEN_CONDITIONS:
        print(f"refused: the conditions ({conditions_sha()}) are not frozen; FROZEN_CONDITIONS is {FROZEN_CONDITIONS}",
              file=sys.stderr)
        return 2
    tasks = {t["pr"]: t for t in es.tasks_of(half)}
    have = kept()
    todo = [c for c in calls(half, arms) if ident({**c, "conditions": conditions_sha()}) not in have]
    print(f"{len(todo)} of {len(calls(half, arms))} calls to make (conditions {conditions_sha()})", file=sys.stderr, flush=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(judge_one, c, tasks[c["pr"]]): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= STOP_AFTER_EMPTY:
                print(f"stopped: {empty} calls in a row gave no verdict", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def kappa(a: list[bool], b: list[bool]) -> float:
    """Cohen's kappa between two judges' broken calls."""
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def table(half: str, arms: tuple[str, ...]) -> list[dict]:
    """Each case with every verdict its arms need, keyed arm/judge; a case missing one is left out."""
    have, sha = kept(), conditions_sha()
    out = []
    for c in cases(half):
        row = {**c}
        for arm in arms:
            for j in JUDGES:
                r = have.get((half, c["pr"], c["lesson"], arm, j, sha if arm == "B" else ""))
                row[f"{arm}/{j}"] = r["verdict"] if r else None
        if all(row[f"{arm}/{j}"] for arm in arms for j in JUDGES):
            out.append(row)
    return out


def broken(rows: list[dict], arm: str, judge: str) -> list[bool]:
    """One judge's calls under one arm, as broken or not."""
    return [r[f"{arm}/{judge}"] == "broken" for r in rows]


def score(half: str, write: bool) -> int:
    """The test half against the bar; the pilot's agreement and each disagreement, for the wording."""
    arms = ("A", "B") if half == "test" else ("B",)
    run_ = run_guard.start()
    rows, sonnet, fable = table(half, arms), "sonnet", "fable"
    out: dict = {"section": "4av", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "half": half,
                 "prompt": dr.SETTLE_SHA, "conditions": conditions_sha(), "frozen": FROZEN_CONDITIONS,
                 "cases": len(cases(half)), "complete": len(rows),
                 "kappa": {arm: round(kappa(broken(rows, arm, sonnet), broken(rows, arm, fable)), 3) for arm in arms},
                 "agree": {arm: sum(r[f"{arm}/{sonnet}"] == r[f"{arm}/{fable}"] for r in rows) for arm in arms},
                 "agree_broken_or_not": {arm: sum(a == b for a, b in zip(broken(rows, arm, sonnet), broken(rows, arm, fable), strict=True))
                                         for arm in arms},
                 "by_key": {key: {"cases": sum(r["key"] == key for r in rows),
                                  **{f"{arm}/{j}": sum(broken([r for r in rows if r["key"] == key], arm, j)) for arm in arms for j in JUDGES},
                                  **{f"{arm}/both": sum(r[f"{arm}/{sonnet}"] == "broken" == r[f"{arm}/{fable}"] for r in rows if r["key"] == key)
                                     for arm in arms}}
                            for key in ("broken", "followed", "related")},
                 "broken_calls": {f"{arm}/{j}": sum(broken(rows, arm, j)) for arm in arms for j in JUDGES}}
    if half == "test":
        gain = kappa(broken(rows, "B", sonnet), broken(rows, "B", fable)) - kappa(broken(rows, "A", sonnet), broken(rows, "A", fable))
        rng, draws = random.Random(SEED), []  # noqa: S311 - a seeded bootstrap
        for _ in range(2000):
            s = [rows[rng.randrange(len(rows))] for _ in rows]
            d = kappa(broken(s, "B", sonnet), broken(s, "B", fable)) - kappa(broken(s, "A", sonnet), broken(s, "A", fable))
            if not math.isnan(d):   # a resample where a judge called everything one way has no kappa
                draws.append(d)
        draws.sort()
        lo, hi = draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]
        keyed = [r for r in rows if r["key"] == "broken"]
        flagged = {arm: sum(r[f"{arm}/{sonnet}"] == "broken" or r[f"{arm}/{fable}"] == "broken" for r in keyed) for arm in arms}
        related = [r for r in rows if r["key"] == "related"]
        alarms = {arm: sum(broken(related, arm, sonnet)) + sum(broken(related, arm, fable)) for arm in arms}
        holds = {"complete": len(rows) >= MIN_COMPLETE, "gain": gain >= KAPPA_GAIN and lo > 0,
                 "not_by_silence": flagged["B"] >= KEEP_FLAGGED * flagged["A"],
                 "not_by_noise": alarms["B"] <= alarms["A"] + EXTRA_ALARMS}
        out |= {"kappa_gain": round(gain, 3), "interval": [round(lo, 3), round(hi, 3)], "key_broken": len(keyed),
                "flagged_by_either": flagged, "related": len(related), "related_broken_calls": alarms, "holds": holds,
                "result": "holds" if all(holds.values()) else "fails"}
    per = {}
    for lesson in lessons():
        mine = [r for r in rows if r["lesson"] == lesson]
        per[lesson] = {arm: f"{sum(r[f'{arm}/{sonnet}'] == r[f'{arm}/{fable}'] for r in mine)}/{len(mine)}" for arm in arms}
    have, sha = kept(), conditions_sha()
    out |= {"per_lesson_agree": per,
            "disagreements": [{"pr": r["pr"], "lesson": r["lesson"], "key": r["key"], "arm": arm,
                               **{j: {"verdict": r[f"{arm}/{j}"],
                                      "reason": have[(half, r["pr"], r["lesson"], arm, j, sha if arm == "B" else "")]["reason"]}
                                  for j in JUDGES}}
                              for r in rows for arm in arms if r[f"{arm}/{sonnet}"] != r[f"{arm}/{fable}"]],
            "api_priced_usd": round(sum(r.get("api_priced_usd", 0) for r in have.values() if r["half"] == half), 2),
            "script_sha256": ba.sha256(Path(__file__))}
    out = run_.stamp(out)
    print(json.dumps({k: out[k] for k in out if k not in ("disagreements", "per_lesson_agree")}, indent=1))
    if write:
        dest = rl.REPO / "evals" / "results" / f"conditions-agree-{half}-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(rl.REPO)}")
    return 0 if len(rows) == len(cases(half)) else 2


def main() -> int:
    """pilot, run or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["pilot", "run", "score"])
    ap.add_argument("--half", choices=["dev", "test"], default="test")
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    if a.step == "pilot":
        return run("dev", ("B",))
    if a.step == "run":
        return run("test", ("A", "B"))
    return score(a.half, a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
