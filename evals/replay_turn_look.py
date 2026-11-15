#!/usr/bin/env python3
"""EXPLORATORY, not pre-registered: §4bg's in-turn ask on §4ay's five tasks, before deciding to run §4bg.

§4ay measured, on §4aw's five tasks, the list of ten (0.08) and the same ten one at a time (0.72). This runs
only the middle: the same ten, in the same order, in one session, asked in one at a time's own words to check
the change against each in turn (`replay_turn.WORDS["turn"]`). Three repeats a task, graded by §4aw's
behaviour graders as §4ay was. It is read against §4ay's receipt, from another day, on tasks six sections have
used, so it is a steer on whether §4bg's run on fourteen new tasks is worth making, never a result.

    python3 evals/replay_turn_look.py run
    python3 evals/replay_turn_look.py score [--receipt]
    python3 evals/replay_turn_look.py dismissals [--receipt]   # what each session said of the right lesson
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_regrade as regrade
import outcome_replay as o
import replay_one as ro
import replay_turn as rt
import run_guard
import sandbox as sb

OUT = o.REPO / "evals" / "bench" / "private" / "realwork" / "outcome-turn-look-4aw.jsonl"
AY = o.REPO / "evals" / "results" / "replay-one-20261111-1355.json"
REPEATS, MODEL, EFFORT = 3, "sonnet", "medium"
ASK_SHA = rt.digest(rt.WORDS["turn"] + o.PROMPT)


def section(task: dict, rep: int) -> str:
    """§4ay's ten in §4ay's order for this repeat, under the in-turn words."""
    body = "\n\n".join(f"<lesson>\n{text}\n</lesson>" for _, text in ro.order(task, rep))
    return f"\n{rt.WORDS['turn']}\n\n<lessons>\n{body}\n</lessons>\n"


def calls() -> list[dict]:
    """Every session: each task, each repeat."""
    return [{"pr": t["pr"], "arm": "turn", "rep": r} for t in o.tasks() for r in range(REPEATS)]


def kept() -> dict[tuple, dict]:
    """Every session kept under this question and these lists."""
    if not OUT.exists():
        return {}
    want = (ASK_SHA, o.sha(ro.rl.LISTS))
    return {o.ident(r): r for r in map(json.loads, OUT.read_text().splitlines())
            if (r.get("ask"), r.get("lists")) == want and r.get("effort") == EFFORT
            and any(MODEL in m for m in r.get("models") or [])}


def session(call: dict, task: dict, before: set[str]) -> dict | None:
    """One in-turn session, then §4aw's grader on the tree it left."""
    start = time.monotonic()
    with o.room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(o.git("diff", task["base"], task["frozen"]))
        got = sb.ask(o.AGENT, o.PROMPT.format(task=o.task_words(task), lesson=section(task, call["rep"])),
                     model=MODEL, effort=EFFORT, timeout=o.TIMEOUT, cwd=room, tree=room)
        if got.get("error"):
            print(f"  #{call['pr']} turn{call['rep']}: {got['error'][-200:]!r}", file=sys.stderr, flush=True)
            return None
        (room / "CHANGE.diff").unlink(missing_ok=True)
        patch = o.patch_of(room)
        harm = [b for b in o.run_tests(room, task)["bad"] if b not in before]
        graded = regrade.grade(room, task)
        room_name = room.name
    return {**call, "ask": ASK_SHA, "lists": o.sha(ro.rl.LISTS), "passed": graded["passed"], "summary": graded["summary"],
            "edited": bool(patch), "harm": harm, "patch": patch[:20000], "said": got["result"][-600:],
            "models": got["models"], "effort": got["effort"], "turns": got["turns"], "usd": got["cost_usd"],
            "room": room_name, "seconds": round(time.monotonic() - start, 1),
            "okl_commit": o.git("rev-parse", "HEAD").strip()}


def run() -> int:
    """Make every session without a result yet; stops when sessions keep failing (a usage limit)."""
    by_pr, have = {t["pr"]: t for t in o.tasks()}, kept()
    before = {p: regrade.frozen_failures(t) for p, t in by_pr.items()}
    todo = [c for c in calls() if o.ident(c) not in have]
    print(f"{len(todo)} of {len(calls())} sessions to run (ask {ASK_SHA})", file=sys.stderr, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=o.WORKERS) as pool:
        futures = {pool.submit(session, c, by_pr[c["pr"]], before[c["pr"]]): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                print(f"  #{row['pr']} turn{row['rep']}: passed {row['passed']}, edited {row['edited']}, "
                      f"{row['seconds']}s", file=sys.stderr, flush=True)
                empty = 0
                continue
            empty += 1
            if empty >= o.STOP_AFTER_EMPTY:
                print(f"stopped: {empty} sessions in a row gave no result", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def score(write: bool) -> int:
    """In turn's pass rate per task, beside §4ay's three arms on the same tasks."""
    guard = run_guard.start()
    rows, prs = list(kept().values()), [t["pr"] for t in o.tasks()]
    ay = json.loads(AY.read_text())["per_task"]
    per_task = {str(p): round(mean(r["passed"] for r in rows if r["pr"] == p), 3) for p in prs
                if any(r["pr"] == p for r in rows)}
    out = {"section": "4bg look (exploratory)", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "ask": ASK_SHA,
           "lists": o.sha(ro.rl.LISTS), "model": MODEL, "effort": EFFORT, "sessions": len(rows), "of": len(calls()),
           "pass_rate_in_turn": round(mean(per_task.values()), 3) if per_task else None,
           "per_task_in_turn": per_task,
           "per_task_4ay": {a: ay[a] for a in ("alone_told", "ten_plain", "one_at_a_time")},
           "pass_rate_4ay": json.loads(AY.read_text())["pass_rate"],
           "edited": sum(r["edited"] for r in rows), "sessions_with_harm": sum(bool(r["harm"]) for r in rows),
           "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None,
           "usd_per_session": round(mean(r["usd"] for r in rows), 3) if rows else None,
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("pr", "rep", "passed", "edited", "harm", "turns", "seconds", "usd",
                                            "effort", "models", "room", "summary", "said")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = o.REPO / "evals" / "results" / f"replay-turn-look-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(o.REPO)}")
    return 0 if len(rows) == len(calls()) else 2


PROJECTS = Path.home() / ".claude" / "projects"
STRONG = 0.8   # the tasks §4ay's one at a time fixed in at least four of five sessions


def said_of(room: str, lesson: str) -> list[str]:
    """What a session wrote about `lesson`, from the transcript Claude Code saved for its room: each
    piece of the agent's own text that names the lesson's id, with what follows it."""
    found = []
    for folder in PROJECTS.glob(f"*{room.replace('_', '-')}*"):
        for log in folder.glob("*.jsonl"):
            for line in log.read_text(errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                content = (event.get("message") or {}).get("content") if event.get("type") == "assistant" else None
                for part in content if isinstance(content, list) else []:
                    text = part.get("text", "") if isinstance(part, dict) and part.get("type") == "text" else ""
                    if lesson in text:
                        i = text.index(lesson)
                        found.append(" ".join(text[i: i + 300].split()))
    return found


def dismissals(write: bool) -> int:
    """On the tasks one at a time nearly always fixed, whether each in-turn session named the right lesson,
    and what it said of it: the figure REPORT §4bg quotes, read from the saved sessions."""
    guard = run_guard.start()
    tasks = {t["pr"]: t for t in o.tasks()}
    strong = sorted(int(p) for p, r in json.loads(AY.read_text())["per_task"]["one_at_a_time"].items() if r >= STRONG)
    rows = []
    for r in sorted(kept().values(), key=lambda x: (x["pr"], x["rep"])):
        if r["pr"] not in strong:
            continue
        said = said_of(r["room"], tasks[r["pr"]]["lesson"])
        rows.append({"pr": r["pr"], "rep": r["rep"], "passed": r["passed"], "room": r["room"],
                     "named": bool(said), "said": said[-1] if said else None})
    out = {"section": "4bg look, what the sessions said", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "tasks": strong, "sessions": len(rows), "failed": sum(not x["passed"] for x in rows),
           "named_and_failed": sum(x["named"] and not x["passed"] for x in rows),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "rows": rows}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    for x in rows:
        print(f"  #{x['pr']} rep{x['rep']} passed={x['passed']} named={x['named']}: {(x['said'] or '')[:160]}")
    if write:
        dest = o.REPO / "evals" / "results" / f"replay-turn-look-dismissals-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        print(f"receipt: {dest.relative_to(o.REPO)}")
    return 0


def main() -> int:
    """run, score, or read what the sessions said."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["run", "score", "dismissals"])
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    if a.step == "dismissals":
        return dismissals(a.receipt)
    return run() if a.step == "run" else score(a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
