#!/usr/bin/env python3
"""REPORT §4bg: is a list's cost its instruction? Ten lessons checked in turn, in one session (#447).

§4ax's list and §4ay's one at a time differed in three ways at once: how many lessons at once, how many
sessions, and what the agent was asked. This adds the middle: the same ten lessons in one session, asked
in one at a time's own words to check the change against each in turn, on new tasks.

Two stages. Stage 1: no lesson, the lesson alone, the list, and in turn. Stage 2 runs only if stage 1
reads "helps": one at a time, with in turn re-run beside it, so the two are compared in one sitting.

    python3 evals/replay_turn.py run --stage 1 [--limit N]
    python3 evals/replay_turn.py score --stage 1 [--receipt]

Every model call goes through sandbox.ask, in a copy of the repository at the frozen commit with one
commit of history. Graders are tests/replay_graders_4bg.py, frozen before any session and checked by
evals/replay_check_4bg.py to fail on the frozen code and pass on the fixed code.
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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_replay as o
import replay_one as ro
import run_guard
import sandbox as sb

REPO = o.REPO
TASKS = REPO / "evals" / "replay-tasks-4bg.json"
LISTS = REPO / "evals" / "replay-lists-4bg.json"
GRADERS = REPO / "tests" / "replay_graders_4bg.py"
OUT = REPO / "evals" / "bench" / "private" / "realwork" / "outcome-turn-4bg.jsonl"
GRADER_IN_ROOM = "tests/test_replay_grader.py"

MODEL, EFFORT, REPEATS, CONTROL_REPEATS, SEED, WORKERS, STOP_AFTER_EMPTY = "sonnet", "medium", 5, 2, 4447, 3, 6
STAGES = {1: ("none", "alone", "list", "turn"), 2: ("one", "turn")}
GAIN, MARGIN, MIN_SHARE, BOOT = 0.25, 0.15, 0.9, 10000
WORDS = {
    "alone": "This team keeps the lesson below.",
    "list": "This team keeps the lessons below.",
    "turn": ("This team keeps the lessons below. Check this change against each of them in turn, in the order given: "
             "if the change breaks it, fix that; if it does not, or the lesson has no bearing on this change, change "
             "nothing for it. Before moving on to the next lesson, write one line naming it by its id and saying what "
             "you found."),
    "one": ro.ASK,
}


def digest(text: str) -> str:
    """A short hash every session carries, so a changed word or file never pools with the old."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


WORDS_SHA = digest(json.dumps(WORDS, sort_keys=True) + o.PROMPT)


def tasks() -> list[dict]:
    """Every task: fourteen with a defect the lesson names, four whose change already followed it."""
    return json.loads(TASKS.read_text())


def inputs() -> dict[str, str]:
    """The hash of everything a session's outcome depends on besides the model."""
    files = {"tasks": TASKS, "lists": LISTS, "graders": GRADERS}
    return {k: o.sha(p) for k, p in files.items()} | {"words": WORDS_SHA}


def calls(stage: int) -> list[dict]:
    """Every planned session of a stage, in a seeded order, so stopping early does not favour an arm."""
    out = []
    for t in tasks():
        reps = CONTROL_REPEATS if t.get("needs_nothing") else REPEATS
        out += [{"stage": stage, "id": t["id"], "pr": t["pr"], "arm": a, "rep": r} for a in STAGES[stage]
                for r in range(reps)]
    random.Random(f"{SEED}-{stage}").shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def ident(row: dict) -> tuple:
    """A session's identity: in turn runs in both stages, and each is its own session."""
    return (row["stage"], row["id"], row["arm"], row["rep"])


def kept(stage: int) -> dict[tuple, dict]:
    """Every session of `stage` kept under these inputs."""
    if not OUT.exists():
        return {}
    want = inputs()
    return {ident(r): r for r in map(json.loads, OUT.read_text().splitlines())
            if r.get("inputs") == want and r.get("stage") == stage}


def position(task: dict, rep: int) -> int:
    """Where the right lesson sits among the ten: seeded per task and repeat, the same in every arm."""
    return random.Random(f"{task['id']}-{rep}").randrange(10)  # noqa: S311  # NOSONAR - seeded on purpose


def ten(task: dict, rep: int) -> list[tuple[bool, str]]:
    """The ten lessons in this session's order, each marked whether it is the right one."""
    others = [(False, x["text"].strip()) for x in json.loads(LISTS.read_text())[task["id"]]["others"]]
    others.insert(position(task, rep), (True, task["lesson_text"].strip()))
    return others


def section(task: dict, arm: str, rep: int) -> str:
    """What an arm is told, beside the change. One at a time is told per pass (`one_session`)."""
    if arm == "none":
        return ""
    if arm in ("list", "turn"):
        body = "\n\n".join(f"<lesson>\n{text}\n</lesson>" for _, text in ten(task, rep))
        return f"\n{WORDS[arm]}\n\n<lessons>\n{body}\n</lessons>\n"
    return f"\n{WORDS[arm]}\n\n<lesson>\n{task['lesson_text'].strip()}\n</lesson>\n"


def prompt(task: dict, lesson: str) -> str:
    """The change, what it is for, and the lesson section."""
    return o.PROMPT.format(task=o.task_words(task), lesson=lesson)


def grade_env(room: Path) -> dict[str, str]:
    """The room's code first, with briefing logging left as the code under test sets it: one grader's
    positive control needs it on."""
    env = sb.clean_env(tree=room)
    env.pop("OKL_BRIEFING_LOG", None)
    return env


def grade(room: Path, task: dict) -> dict:
    """The task's frozen grader on the tree the session left: exit 0 is a pass."""
    (room / GRADER_IN_ROOM).parent.mkdir(parents=True, exist_ok=True)
    (room / GRADER_IN_ROOM).write_text(GRADERS.read_text())
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line", "-rfE",
                        f"{GRADER_IN_ROOM}::{task['grader']}"], cwd=room, capture_output=True, text=True,
                       env=grade_env(room), timeout=o.TIMEOUT)
    tail = p.stdout.strip().splitlines()[-1:] if p.stdout.strip() else [p.stderr.strip()[-200:]]
    (room / GRADER_IN_ROOM).unlink(missing_ok=True)
    return {"passed": p.returncode == 0, "exit": p.returncode, "summary": tail[0]}


def harm_files(task: dict) -> list[str]:
    """The test files the real fix touched that already exist at the frozen commit: where a session's
    edit could break something the change's own tests check."""
    changed = o.git("diff", "--name-only", task["frozen"], task["end"]).split() if task["end"] != task["frozen"] else []
    there = set(o.git("ls-tree", "-r", "--name-only", task["frozen"], "tests").split())
    return sorted(f for f in changed if f.startswith("tests/") and f.endswith(".py") and f in there)


def failing(room: Path, files: list[str]) -> set[str]:
    """Tests in `files` that do not pass on the room's tree."""
    if not files:
        return set()
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", "-rfE", *files],
                       cwd=room, capture_output=True, text=True, env=grade_env(room), timeout=o.TIMEOUT)
    return {m.group(2) for line in p.stdout.splitlines() if (m := re.match(r"^(FAILED|ERROR) (\S+)", line))}


def frozen_failures(task: dict) -> set[str]:
    """What already fails at the frozen commit, so a session is charged only for what it broke."""
    with o.room_at(task["frozen"]) as room:
        return failing(room, harm_files(task))


def ask(room: Path, text: str, name: str) -> dict | None:
    """One fresh session in the room; None, and why on stderr, when it gave no usable reply."""
    got = sb.ask(o.AGENT, text, model=MODEL, effort=EFFORT, timeout=o.TIMEOUT, cwd=room, tree=room,
                 unset=("OKL_BRIEFING_LOG",))
    if got.get("error"):
        print(f"  {name}: {got['error'][-200:]!r}", file=sys.stderr, flush=True)
        return None
    return got


def changed_files(room: Path) -> list[str]:
    """Paths the session added, changed or removed."""
    return sorted(line[3:] for line in o.git("status", "--porcelain", cwd=room).splitlines())


def finish(room: Path, task: dict, before: set[str]) -> dict:
    """What the session left: the files and patch, what it broke, and the grader's verdict."""
    (room / "CHANGE.diff").unlink(missing_ok=True)
    changed = changed_files(room)
    patch = o.patch_of(room)
    harm = sorted(failing(room, harm_files(task)) - before)
    got = grade(room, task)
    return {"passed": got["passed"], "grader_exit": got["exit"], "summary": got["summary"], "edited": bool(patch),
            "changed": changed, "harm": harm, "patch_chars": len(patch), "patch": patch[:20000]}


def single_session(call: dict, task: dict, before: set[str]) -> dict | None:
    """Every arm but one at a time: one session, then the grader."""
    start = time.monotonic()
    with o.room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(o.git("diff", task["base"], task["frozen"]))
        got = ask(room, prompt(task, section(task, call["arm"], call["rep"])), f"{call['id']} {call['arm']}{call['rep']}")
        if got is None:
            return None
        row = finish(room, task, before)
        room_name = room.name
    return {**call, **row, "said": got["result"][-600:], "models": got["models"], "effort": got["effort"],
            "turns": got["turns"], "usd": got["cost_usd"], "room": room_name,
            "seconds": round(time.monotonic() - start, 1)}


def one_session(call: dict, task: dict, before: set[str]) -> dict | None:
    """Ten fresh sessions in one working copy, one lesson each in the list's order, then the grader."""
    start, passes = time.monotonic(), []
    with o.room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(o.git("diff", task["base"], task["frozen"]))
        for i, (right, text) in enumerate(ten(task, call["rep"])):
            was = ro.state(room)
            got = ask(room, prompt(task, f"\n{WORDS['one']}\n\n<lesson>\n{text}\n</lesson>\n"),
                      f"{call['id']} one{call['rep']} pass {i}")
            if got is None:
                return None
            passes.append({"position": i, "right": right, "edited": ro.state(room) != was, "turns": got["turns"],
                           "usd": got["cost_usd"], "models": got["models"], "said": got["result"][-300:]})
        row = finish(room, task, before)
        room_name = room.name
    others = [p for p in passes if not p["right"]]
    return {**call, **row, "passes": passes, "right_edited": any(p["edited"] for p in passes if p["right"]),
            "other_edits": sum(p["edited"] for p in others), "effort": EFFORT, "room": room_name,
            "models": sorted({m for p in passes for m in p["models"]}), "usd": sum(p["usd"] for p in passes),
            "seconds": round(time.monotonic() - start, 1)}


def session(call: dict, task: dict, before: set[str]) -> dict | None:
    """One planned session of any arm, stamped with what it ran under."""
    row = (one_session if call["arm"] == "one" else single_session)(call, task, before)
    return {**row, "inputs": inputs(), "okl_commit": o.git("rev-parse", "HEAD").strip()} if row else None


def preflight() -> list[str]:
    """Every reference a session will follow, resolved before the first one runs (lesson n_aa3e45a2ecd6):
    a list and a grader for each task. And committed code, since the run reads this tree while it works
    (lesson harness-reads-a-moving-working-tree): run it from a worktree pinned to the pre-registered
    commit. Returns what is wrong; empty when it may start."""
    ts, graders = tasks(), GRADERS.read_text()
    lists = json.loads(LISTS.read_text()) if LISTS.exists() else {}
    wrong = [f"{t['id']}: no list" for t in ts if t["id"] not in lists]
    wrong += [f"{t['id']}: no grader {t['grader']}" for t in ts if f"def {t['grader']}(" not in graders]
    label = run_guard.start().started[0]
    if label is None or label.endswith("+dirty"):
        wrong.append(f"the code this run reads is not committed ({label})")
    if REPO.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        # lesson commit-wip-in-tmp-worktrees: macOS clears the temp folder at boot, and the sessions this
        # run keeps are uncommitted, so a reboot mid-run would lose every one
        wrong.append(f"this tree is in the temp folder ({REPO}), which a reboot clears: run from a worktree "
                     "outside it")
    return wrong


def stage_two_allowed() -> bool:
    """Stage 2 runs only when stage 1, complete, read "helps", as pre-registered."""
    return verdict(1).get("reading") == "helps"


def run(stage: int, limit: int | None) -> int:
    """Make every planned session of `stage` without a result; stops when sessions keep failing (a usage
    limit). Stage 2 refuses to start unless stage 1 read "helps"."""
    wrong = preflight()
    if stage == 2 and not stage_two_allowed():
        wrong.append("stage 1 did not read \"helps\", so stage 2 is not run (as pre-registered)")
    if wrong:
        raise SystemExit("not starting:\n  " + "\n  ".join(wrong))
    by_id, have = {t["id"]: t for t in tasks()}, kept(stage)
    todo = [c for c in calls(stage) if ident(c) not in have][:limit]
    print(f"stage {stage}: {len(todo)} of {len(calls(stage))} sessions to run ({inputs()})", file=sys.stderr, flush=True)
    before = {i: frozen_failures(t) for i, t in by_id.items() if any(c["id"] == i for c in todo)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(session, c, by_id[c["id"]], before[c["id"]]): c for c in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= STOP_AFTER_EMPTY:
                print(f"stopped: {empty} sessions in a row gave no result", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def interval(diffs: list[float], level: float, seed: str) -> tuple[float, float]:
    """Percentile interval of the mean paired difference, resampling tasks (the unit), seeded."""
    rng = random.Random(seed)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(BOOT))
    return round(means[int((1 - level) / 2 * BOOT)], 3), round(means[min(BOOT - 1, int((1 + level) / 2 * BOOT))], 3)


def per_task(rows: list[dict], planned: list[dict], arm: str, ids: list[str], fill: bool | None) -> dict[str, float]:
    """Each task's pass rate in `arm`. A planned session with no row counts as `fill` (True a pass, False
    a fail), or is left out when `fill` is None."""
    got = {ident(r): r["passed"] for r in rows if r["arm"] == arm}
    out = {}
    for i in ids:
        mine = [c for c in planned if c["arm"] == arm and c["id"] == i]
        vals = [float(v) for v in (got.get(ident(c), fill) for c in mine) if v is not None]
        out[i] = mean(vals) if vals else 0.0
    return out


def by_change(diffs: dict[str, float], level: float, seed: str) -> tuple[float, float]:
    """The same interval resampling changes instead of tasks: two tasks that share a frozen change move
    together, so they are drawn together (reported beside, not read)."""
    change = {t["id"]: t["frozen"] for t in tasks()}
    groups: dict[str, list[float]] = {}
    for i, d in diffs.items():
        groups.setdefault(change.get(i, i), []).append(d)
    clusters = list(groups.values())
    rng = random.Random(seed)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    means = []
    for _ in range(BOOT):
        drawn = [d for g in rng.choices(clusters, k=len(clusters)) for d in g]
        means.append(sum(drawn) / len(drawn))
    means.sort()
    return round(means[int((1 - level) / 2 * BOOT)], 3), round(means[min(BOOT - 1, int((1 + level) / 2 * BOOT))], 3)


def contrast(rows: list[dict], planned: list[dict], a: str, b: str, ids: list[str]) -> dict:
    """`a` minus `b`, paired by task: the mean and its intervals with missing sessions counted against
    `a` beating `b` (the reading) and for it (the best case), and the reading's interval by change."""
    out = {}
    for case, (fa, fb) in {"against": (False, True), "for": (True, False), "as_run": (None, None)}.items():
        ra, rb = per_task(rows, planned, a, ids, fa), per_task(rows, planned, b, ids, fb)
        diffs = [ra[i] - rb[i] for i in ids]
        seed = f"{a}-{b}-{case}"
        out[case] = {"mean": round(mean(diffs), 3), "ci95": interval(diffs, 0.95, seed),
                     "ci90": interval(diffs, 0.90, seed)}
        if case == "against":
            out[case]["ci95_by_change"] = by_change({i: ra[i] - rb[i] for i in ids}, 0.95, seed)
    return out


def read_stage_1(c: dict[str, dict], complete: bool) -> dict[str, str]:
    """Stage 1's stated readings, on the intervals with missing sessions counted against each claim."""
    if not complete:
        return {"reading": "not complete"}
    cost, gain = c["alone-list"]["against"], c["turn-list"]["against"]
    if cost["ci95"][0] <= 0:
        return {"reading": "the list did not cost on these tasks"}
    lo, hi = gain["ci95"]
    if lo > 0:
        return {"reading": "helps" if hi >= GAIN else "helps, under the bar"}
    return {"reading": "does not help enough to act on" if hi < GAIN else "inconclusive"}


def read_stage_2(c: dict[str, dict], complete: bool) -> dict[str, str]:
    """Stage 2's stated reading, a pilot: in turn against one at a time, in the same sitting."""
    if not complete:
        return {"reading": "not complete"}
    lo90, hi90 = c["turn-one"]["against"]["ci90"]
    return {"reading": "not worse" if lo90 > -MARGIN else "worse" if hi90 < -MARGIN else "inconclusive"}


PAIRS = {1: (("alone", "list"), ("turn", "list"), ("alone", "none"), ("turn", "none")), 2: (("turn", "one"),)}


def tally(stage: int) -> dict:
    """A stage's rows, plan, contrasts on the broken tasks, and its reading."""
    rows, planned, ts = list(kept(stage).values()), calls(stage), tasks()
    broken = [t["id"] for t in ts if not t.get("needs_nothing")]
    controls = [t["id"] for t in ts if t.get("needs_nothing")]
    arms = STAGES[stage]
    done = {a: sum(r["arm"] == a and r["id"] in broken for r in rows) for a in arms}
    plan = {a: sum(c["arm"] == a and c["id"] in broken for c in planned) for a in arms}
    complete = all(done[a] >= MIN_SHARE * plan[a] for a in arms)
    c = {f"{a}-{b}": contrast(rows, planned, a, b, broken) for a, b in PAIRS[stage]}
    reading = (read_stage_1 if stage == 1 else read_stage_2)(c, complete)
    return {"rows": rows, "planned": planned, "broken": broken, "controls": controls, "done": done, "plan": plan,
            "contrasts": c, "reading": reading}


def verdict(stage: int) -> dict[str, str]:
    """A stage's reading from the sessions kept so far."""
    return tally(stage)["reading"]


def score(stage: int, write: bool) -> int:
    """A stage's pass rates per arm, its stated contrasts and reading, noise, harm, cost and time."""
    guard = run_guard.start()
    t = tally(stage)
    rows, planned, broken, controls = t["rows"], t["planned"], t["broken"], t["controls"]
    arms = STAGES[stage]
    of = lambda a, ids: [r for r in rows if r["arm"] == a and r["id"] in ids]  # noqa: E731
    ones = of("one", broken + controls)
    out = {"section": "4bg", "stage": stage, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "inputs": inputs(),
           "model": MODEL, "effort": EFFORT, "sessions": len(rows), "of": len(planned),
           "done_per_arm": t["done"], "planned_per_arm": t["plan"],
           "pass_rate": {a: round(mean(per_task(rows, planned, a, broken, None).values()), 3) for a in arms},
           "per_task": {a: per_task(rows, planned, a, broken, None) for a in arms},
           "contrasts": t["contrasts"], "reading": t["reading"],
           "controls_broken": {a: sum(not r["passed"] for r in of(a, controls)) for a in arms},
           "controls_sessions": {a: len(of(a, controls)) for a in arms},
           "sessions_with_harm": {a: sum(bool(r["harm"]) for r in rows if r["arm"] == a) for a in arms},
           "edited": {a: sum(r["edited"] for r in of(a, broken)) for a in arms},
           "one_other_edits_median": median(r["other_edits"] for r in ones) if ones else None,
           "one_other_edits_total": sum(r["other_edits"] for r in ones),
           "usd_per_session": {a: round(mean(r["usd"] for r in rows if r["arm"] == a), 3) for a in arms
                               if any(r["arm"] == a for r in rows)},
           "median_seconds": {a: median(r["seconds"] for r in rows if r["arm"] == a) for a in arms
                              if any(r["arm"] == a for r in rows)},
           "api_priced_usd": round(sum(r["usd"] for r in rows), 2),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("stage", "id", "pr", "arm", "rep", "passed", "grader_exit", "edited",
                                            "changed", "harm", "right_edited", "other_edits", "seconds", "usd",
                                            "effort", "models", "room", "summary")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("rows", "per_task")}, indent=1))
    if write:
        dest = REPO / "evals" / "results" / f"replay-turn-s{stage}-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0 if len(rows) == len(planned) else 2


def main() -> int:
    """run or score a stage."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["run", "score"])
    ap.add_argument("--stage", type=int, choices=sorted(STAGES), required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return run(a.stage, a.limit) if a.step == "run" else score(a.stage, a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
