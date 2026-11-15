#!/usr/bin/env python3
"""REPORT §4bj: the review after writing against no review, on the graded replay set's 43 broken tasks.

§4az measured the review end to end on five tasks, too few to decide anything (#457). This runs the same
comparison on §4bg's and §4bi's tasks: each session is asked to get a past change ready to merge, as first
written, and in the review arm also to run the repository's review after writing, as `okl check --change`
prints it today, over the lessons that existed when the change was made. Nothing hands the agent the right
lesson; it picks from all of them. Each task's grader, checked to fail on the frozen code and pass on the
fixed (evals/replay_check_4bg.py), reads the tree the session leaves.

    python3 evals/review_graded.py build [--store PATH] [--write]   # each task's review, rendered once
    python3 evals/review_graded.py check [--receipt]                # the graders, through this harness
    python3 evals/review_graded.py run [--limit N]
    python3 evals/review_graded.py score [--receipt]

`build` renders every task's review into a private folder and, with --write, records each one's hash in
evals/review-graded-4bj.json; `run` refuses a review that is not the one recorded there.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import default_read as dr
import outcome_replay as o
import replay_check_4bg as rc
import replay_lists_4bg as rl
import replay_turn as rt
import run_guard
import sandbox as sb

from okl import core

REPO = o.REPO
SETS = ("4bg", "457")
MANIFEST = REPO / "evals" / "review-graded-4bj.json"
BUILT = REPO / "evals" / "bench" / "private" / "realwork" / "review-graded-4bj"
OUT = REPO / "evals" / "bench" / "private" / "realwork" / "review-graded-4bj.jsonl"
STORE = REPO / ".okl" / "okl.db"

ARMS = ("none", "review")
MODEL, EFFORT, REPEATS, SEED, WORKERS, STOP_AFTER_EMPTY = "sonnet", "medium", 2, 4457, 3, 3
TIMEOUT = 3 * o.TIMEOUT   # a review starts up to ten sub-agents one after another (§4az's ran 214 s at the median)
GAIN, EXTRA_HARM, FOLLOWED, MIN_SHARE, BOOT = 0.25, 2, 0.5, 0.9, 10000
# §4az's request, word for word: the review's output is a file, and okl is not installed in the copy.
ASK = f"""
Before you finish, this repository asks you to run its review after writing. Its output, as `okl check --change` prints it for this change, is in {dr.LIST_FILE}: follow its steps. okl is not installed in this copy, so wherever a step says `okl show <id>`, read the lesson's full text at {dr.LESSON_DIR}/<id>.md instead.
"""
# Both arms run with the same tools, the sub-agent tool among them, so the arms differ only by the request.
AGENT = ["claude", "-p", "--model", MODEL, "--output-format", "stream-json", "--verbose", "--restricted",
         "--strict-mcp-config", "--tools", "Read,Grep,Glob,Edit,Write,Bash,Agent",
         "--allowedTools", "Read", "Grep", "Glob", "Edit", "Write", "Agent", "Bash(python3 -m pytest *)",
         "Bash(git diff *)", "Bash(git status *)"]
WORDS_SHA = hashlib.sha256(json.dumps([o.PROMPT, ASK, AGENT, list(core.REVIEW_STEPS)]).encode()).hexdigest()[:16]


def tasks() -> list[dict[str, Any]]:
    """Every task of both sets: 43 with a defect the lesson names, five whose change already followed it."""
    return [t for _, t in rc.load(list(SETS))]


def inputs() -> dict[str, str]:
    """The hash of everything a session's outcome depends on besides the model."""
    files = {f"{kind}_{name}": rc.set_paths(name)[kind] for name in SETS for kind in ("tasks", "graders")}
    files["manifest"] = MANIFEST
    return {k: o.sha(p) for k, p in files.items()} | {"words": WORDS_SHA}


# --- the review each task is given -------------------------------------------------------------------

def frozen_ms(task: dict[str, Any]) -> int:
    """When the task's frozen commit was made, in the store's epoch milliseconds."""
    return rl.frozen_ms(task["frozen"])


def redact(con: sqlite3.Connection, task: dict[str, Any]) -> None:
    """The right lesson's words without the clauses that name this task's own fix, PR or incident, as its
    lesson_text has them (§4bg, §4bi). A redaction that matches nothing is refused: the review would then
    show a clause the task file says was removed."""
    fields = ("title", "symptom", "fix", "body")
    row = dict(zip(fields, con.execute("select title, symptom, fix, body from node where id = ?",
                                       (task["lesson"],)).fetchone(), strict=True))
    for r in task.get("lesson_redactions") or []:
        removed, field = r["removed"], r.get("field")
        if field is None and removed.startswith("body: "):
            field, removed = "body", removed[len("body: "):]
        hits = [f for f in ([field] if field else fields) if removed in (row[f] or "")]
        if not hits:
            raise SystemExit(f"{task['id']}: a redaction matches nothing in {task['lesson']}: {removed[:60]!r}")
        for f in hits:
            row[f] = row[f].replace(removed, "")
    con.execute("update node set title = ?, symptom = ?, fix = ?, body = ? where id = ?",
                (*[row[f] for f in fields], task["lesson"]))


def cites(text: str, task: dict[str, Any]) -> bool:
    """Whether a lesson's words name the task's own change or fix: its PR as a whole number, its grader,
    or the fixing commit. The lists did the same (replay_lists_4bg.build), there by plain substring."""
    return bool(re.search(rf"#{task['pr']}(?!\d)", text)) or task["grader"] in text or task["end"][:7] in text


def as_they_stood(snapshot: Path, db: Path, task: dict[str, Any]) -> dict[str, Any]:
    """`db`: the lessons as they stood at the frozen commit (replay_lists_4bg.as_they_stood), with the
    right lesson kept even when it was written later, its words redacted, verification after then
    undone, and every other lesson that names this task's change or fix left out."""
    when = frozen_ms(task)
    rl.as_they_stood(snapshot, db, when)
    with contextlib.closing(sqlite3.connect(db)) as con:
        later = con.execute("select count(*) from node where id = ?", (task["lesson"],)).fetchone()[0] == 0
        if later:
            con.execute("attach database ? as src", (str(snapshot),))
            con.execute("insert into node select * from src.node where id = ?", (task["lesson"],))
            con.commit()
            con.execute("detach database src")
        redact(con, task)
        con.execute("update node set verified_at = null, verified_by = null, verified_commit = null "
                    "where verified_at > ?", (when,))
        con.commit()
    words = dr.full_text(db)
    dropped = sorted(i for i, text in words.items() if i != task["lesson"] and cites(text, task))
    with contextlib.closing(sqlite3.connect(db)) as con:
        con.executemany("delete from node where id = ?", [(i,) for i in dropped])
        con.commit()
    left = dr.full_text(db)[task["lesson"]]
    for r in task.get("lesson_redactions") or []:
        assert r["removed"].removeprefix("body: ") not in left, f"{task['id']}: a redacted clause survived"
    return {"right_written_later": later, "dropped_citing_the_change": dropped}


def build_one(task: dict[str, Any], snapshot: Path, side: Path) -> dict[str, Any]:
    """One task's review, rendered as `okl check --change` prints it, into BUILT/<id>; its manifest row."""
    db = side / f"store-{task['id']}.db"
    facts = as_they_stood(snapshot, db, task)
    files = dr.changed_files(o.git("diff", task["base"], task["frozen"]))
    text = dr.review_text(task, db, files)
    words = dr.full_text(db)
    here = BUILT / task["id"]
    shutil.rmtree(here, ignore_errors=True)
    (here / "lessons").mkdir(parents=True)
    (here / "REVIEW.md").write_text(text)
    for i, body in words.items():
        (here / "lessons" / f"{i.replace('/', '_')}.md").write_text(body)
    menu = re.findall(r"\[([^\]\s]+)\]", text)
    lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    right_line = next((n for n, ln in enumerate(lines, 1) if f"[{task['lesson']}]" in ln), None)
    governs = f"[{task['lesson']}]" in text.split("### Every")[0]
    return {"id": task["id"], "set": task["set"], "lesson": task["lesson"], "lessons_listed": len(lines),
            "right_listed_at": right_line, "right_governs_a_changed_file": governs,
            "changed_files": files, "ids_named": len(set(menu)), **facts,
            "review_sha256": hashlib.sha256(text.encode()).hexdigest(), "lessons_sha256": lessons_sha(here)}


def lessons_sha(here: Path) -> str:
    """One hash over a task's lesson files, names and words."""
    h = hashlib.sha256()
    for f in sorted((here / "lessons").iterdir()):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def build(store: Path, write: bool) -> int:
    """Every task's review, from a read-only copy of `store`; prints each, and records the hashes with --write."""
    rows = []
    with tempfile.TemporaryDirectory(prefix="okl-4bj-") as side:
        snapshot = Path(side) / "store.db"
        sb.copy_sqlite(store, snapshot)
        with contextlib.closing(sqlite3.connect(snapshot)) as con:
            nodes, newest = con.execute("select count(*), max(created_at) from node").fetchone()
        for t in tasks():
            row = build_one(t, snapshot, Path(side))
            rows.append(row)
            print(f"{t['id']}: {row['lessons_listed']} lessons, right one at line {row['right_listed_at']}"
                  f"{' (governs a changed file)' if row['right_governs_a_changed_file'] else ''}"
                  f"{', written later' if row['right_written_later'] else ''}, "
                  f"{len(row['dropped_citing_the_change'])} left out for citing the change")
    missing = [r["id"] for r in rows if r["right_listed_at"] is None]
    if missing:
        raise SystemExit(f"the right lesson is not in the review for {missing}")
    if write:
        store_row = {"records": nodes, "newest_created_at": newest}
        MANIFEST.write_text(json.dumps({"store": store_row, "tasks": rows}, indent=1) + "\n")
        print(f"wrote {MANIFEST.relative_to(REPO)}")
    return 0


# --- sessions ----------------------------------------------------------------------------------------

def calls() -> list[dict[str, Any]]:
    """Every planned session, in a seeded order, so stopping early does not favour an arm."""
    out = [{"id": t["id"], "pr": t["pr"], "set": t["set"], "arm": a, "rep": r}
           for t in tasks() for a in ARMS for r in range(REPEATS)]
    random.Random(SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def ident(row: dict[str, Any]) -> tuple[str, str, int]:
    """A session's identity."""
    return (row["id"], row["arm"], row["rep"])


def kept() -> dict[tuple, dict[str, Any]]:
    """Every session kept under these inputs, model and effort."""
    if not OUT.exists():
        return {}
    want = inputs()
    return {ident(r): r for r in map(json.loads, OUT.read_text().splitlines())
            if r.get("inputs") == want and r.get("effort") == EFFORT and any(MODEL in m for m in r.get("models") or [])}


def grade(room: Path, task: dict[str, Any]) -> dict[str, Any]:
    """The task's grader, from its own set's module, on the tree in `room`: exit 0 is a pass. As
    replay_turn.grade, which reads §4bg's module only."""
    graders = rc.set_paths(task["set"])["graders"]
    (room / rt.GRADER_IN_ROOM).parent.mkdir(parents=True, exist_ok=True)
    (room / rt.GRADER_IN_ROOM).write_text(graders.read_text())
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line", "-rfE",
                            f"{rt.GRADER_IN_ROOM}::{task['grader']}"], cwd=room, capture_output=True, text=True,
                           env=rt.grade_env(room), timeout=o.TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"passed": False, "exit": None, "summary": f"the grader did not finish in {o.TIMEOUT}s"}
    finally:
        (room / rt.GRADER_IN_ROOM).unlink(missing_ok=True)
    tail = p.stdout.strip().splitlines()[-1:] if p.stdout.strip() else [p.stderr.strip()[-200:]]
    return {"passed": p.returncode == 0, "exit": p.returncode, "summary": tail[0]}


def finish(room: Path, task: dict[str, Any], before: set[str]) -> dict[str, Any]:
    """What the session left, the review's files removed first: the files and patch, what it broke among
    the tests the real fix touched, and the grader's verdict."""
    for extra in ("CHANGE.diff", dr.LIST_FILE):
        (room / extra).unlink(missing_ok=True)
    shutil.rmtree(room / dr.LESSON_DIR, ignore_errors=True)
    changed = rt.changed_files(room)
    patch = o.patch_of(room)
    try:
        harm: list[str] | None = sorted(rt.failing(room, rt.harm_files(task)) - before)
    except subprocess.TimeoutExpired:
        harm = None
    got = grade(room, task)
    return {"passed": got["passed"], "grader_exit": got["exit"], "summary": got["summary"], "edited": bool(patch),
            "changed": changed, "harm": harm, "patch_chars": len(patch), "patch": patch[:20000]}


def right_checked(task: dict[str, Any], agents: list[dict[str, Any]]) -> bool:
    """Whether a sub-agent the session started was handed the right lesson, by its id or its file."""
    return any(task["lesson"] in json.dumps(a) or task["lesson"].replace("/", "_") in json.dumps(a) for a in agents)


def session(call: dict[str, Any], task: dict[str, Any], before: set[str]) -> dict[str, Any] | None:
    """One session in a copy at the frozen commit, then the grader. Dropped (no row, so a later run repeats
    it) when it gave no usable reply or its inputs changed while it ran."""
    stamp, start, name = inputs(), time.monotonic(), f"{call['id']} {call['arm']}{call['rep']}"
    with o.room_at(task["frozen"]) as room:
        (room / "CHANGE.diff").write_text(o.git("diff", task["base"], task["frozen"]))
        ask = ""
        if call["arm"] == "review":
            shutil.copy(BUILT / task["id"] / "REVIEW.md", room / dr.LIST_FILE)
            shutil.copytree(BUILT / task["id"] / "lessons", room / dr.LESSON_DIR)
            ask = ASK
        got = sb.ask(AGENT, rt.prompt(task, ask), model=MODEL, effort=EFFORT, timeout=TIMEOUT, cwd=room, tree=room,
                     unset=("OKL_BRIEFING_LOG",))
        if got.get("error"):
            print(f"  {name}: {got['error'][-200:]!r}", file=sys.stderr, flush=True)
            return None
        row = finish(room, task, before)
        room_name = room.name
    if inputs() != stamp:
        print(f"  {name}: its inputs changed while it ran; dropped", file=sys.stderr, flush=True)
        return None
    agents = got.get("agent_inputs") or []
    return {**call, **row, "sub_agents": got.get("sub_agents", 0), "right_checked": right_checked(task, agents),
            "agent_inputs": [json.dumps(a)[:600] for a in agents], "said": got["result"][-600:],
            "models": got["models"], "effort": got["effort"], "turns": got["turns"], "usd": got["cost_usd"],
            "room": room_name, "seconds": round(time.monotonic() - start, 1), "inputs": stamp,
            "okl_commit": o.git("rev-parse", "HEAD").strip()}


def built_as_recorded() -> list[str]:
    """Each task whose rendered review is missing or differs from the manifest's hash."""
    if not MANIFEST.exists():
        return ["no manifest: run `build --write` and commit it"]
    rows = {r["id"]: r for r in json.loads(MANIFEST.read_text())["tasks"]}
    wrong = []
    for t in tasks():
        here, want = BUILT / t["id"], rows.get(t["id"])
        if want is None or not (here / "REVIEW.md").exists():
            wrong.append(f"{t['id']}: not built")
        elif (hashlib.sha256((here / "REVIEW.md").read_bytes()).hexdigest() != want["review_sha256"]
              or lessons_sha(here) != want["lessons_sha256"]):
            wrong.append(f"{t['id']}: built review differs from the manifest")
    return wrong


def preflight() -> list[str]:
    """What stops a run: a review not as recorded, a missing grader, uncommitted code, or a tree a reboot
    clears (as replay_turn.preflight)."""
    wrong = built_as_recorded()
    for t in tasks():
        if f"def {t['grader']}(" not in rc.set_paths(t["set"])["graders"].read_text():
            wrong.append(f"{t['id']}: no grader {t['grader']}")
    label = run_guard.start().started[0]
    if label is None or label.endswith("+dirty"):
        wrong.append(f"the code this run reads is not committed ({label})")
    if REPO.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        wrong.append(f"this tree is in the temp folder ({REPO}), which a reboot clears")
    return wrong


def run(limit: int | None) -> int:
    """Make every planned session without a result; stops after a few in a row give no result, which is
    what a usage limit looks like (lesson eval-run-stop-at-usage-limit), and says how to resume."""
    wrong = preflight()
    if wrong:
        raise SystemExit("not starting:\n  " + "\n  ".join(wrong))
    by_id, have = {t["id"]: t for t in tasks()}, kept()
    todo = [c for c in calls() if ident(c) not in have][:limit]
    print(f"{len(todo)} of {len(calls())} sessions to run ({inputs()})", file=sys.stderr, flush=True)
    before = {i: rt.frozen_failures(t) for i, t in by_id.items() if any(c["id"] == i for c in todo)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty, made = 0, 0
    with OUT.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(session, c, by_id[c["id"]], before[c["id"]]): c for c in todo}
        for f in as_completed(futures):
            c = futures[f]
            try:
                row = f.result()
            except Exception as e:  # noqa: BLE001 - one session's crash must not lose the others' rows
                print(f"  {c['id']} {c['arm']}{c['rep']}: {e!r}", file=sys.stderr, flush=True)
                row = None
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                made, empty = made + 1, 0
                print(f"  [{made}/{len(todo)}] {c['id']} {c['arm']}{c['rep']}: "
                      f"{'pass' if row['passed'] else 'fail'}, {row['sub_agents']} sub-agents, {row['seconds']}s",
                      file=sys.stderr, flush=True)
                continue
            empty += 1
            if empty >= STOP_AFTER_EMPTY:
                print(f"stopped: {empty} sessions in a row gave no result, which is what a usage limit looks like; "
                      "run again to resume where it stopped", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def check(write: bool) -> int:
    """Each grader through this harness's own grading, with no session: a broken task fails at its frozen
    commit and passes at its fix, a control passes at its frozen commit. replay_check_4bg proves the
    graders; this proves the path a session's verdict takes."""
    guard, rows = run_guard.start(), []
    for t in tasks():
        with o.room_at(t["frozen"]) as room:
            frozen = grade(room, t)
        end = None
        if not t.get("needs_nothing"):
            with o.room_at(t["end"]) as room:
                end = grade(room, t)
        ok = frozen["passed"] if t.get("needs_nothing") else (not frozen["passed"] and end is not None and end["passed"])
        rows.append({"id": t["id"], "set": t["set"], "control": bool(t.get("needs_nothing")), "ok": ok,
                     "frozen_passed": frozen["passed"], "end_passed": end["passed"] if end else None,
                     "frozen_summary": rc.TEMP_PATH.sub("<tmp>", frozen["summary"])})
        print(f"{t['id']}: {'ok' if ok else 'WRONG'}", flush=True)
    wrong = [r["id"] for r in rows if not r["ok"]]
    out = guard.stamp({"section": "4bj", "step": "check", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                       "inputs": inputs(), "tasks": len(rows), "read_as_checked": len(rows) - len(wrong),
                       "wrong": wrong, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "rows": rows})
    print(f"{out['read_as_checked']} of {len(rows)} graders read as checked; wrong: {wrong}")
    if write:
        dest = REPO / "evals" / "results" / f"review-graded-check-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 1 if wrong else 0


# --- the reading -------------------------------------------------------------------------------------

def per_task(rows: list[dict], arm: str, ids: list[str], fill: bool | None) -> dict[str, float]:
    """Each task's pass rate in `arm`. A planned session with no row counts as `fill` (True a pass, False a
    fail), or is left out when `fill` is None."""
    got = {ident(r): r["passed"] for r in rows if r["arm"] == arm}
    out = {}
    for i in ids:
        vals = [float(v) for v in (got.get((i, arm, r), fill) for r in range(REPEATS)) if v is not None]
        out[i] = mean(vals) if vals else 0.0
    return out


def by_change(diffs: dict[str, float], level: float, seed: str) -> tuple[float, float]:
    """The interval resampling frozen changes instead of tasks: tasks that share a change move together
    (reported beside the reading, not read)."""
    change = {t["id"]: t["frozen"] for t in tasks()}
    groups: dict[str, list[float]] = {}
    for i, d in diffs.items():
        groups.setdefault(change[i], []).append(d)
    clusters = list(groups.values())
    rng = random.Random(seed)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    means = sorted(mean([d for g in rng.choices(clusters, k=len(clusters)) for d in g]) for _ in range(BOOT))
    return round(means[int((1 - level) / 2 * BOOT)], 3), round(means[min(BOOT - 1, int((1 + level) / 2 * BOOT))], 3)


def contrast(rows: list[dict], ids: list[str]) -> dict[str, dict]:
    """The review minus none, paired by task: missing sessions counted against the review (the reading),
    for it, and left out."""
    out = {}
    for case, (fa, fb) in {"against": (False, True), "for": (True, False), "as_run": (None, None)}.items():
        ra, rb = per_task(rows, "review", ids, fa), per_task(rows, "none", ids, fb)
        diffs = {i: ra[i] - rb[i] for i in ids}
        seed = f"4bj-{case}"
        out[case] = {"mean": round(mean(diffs.values()), 3), "ci95": rt.interval(list(diffs.values()), 0.95, seed),
                     "ci90": rt.interval(list(diffs.values()), 0.90, seed)}
        if case == "against":
            out[case]["ci95_by_change"] = by_change(diffs, 0.95, seed)
    return out


def reading(c: dict[str, dict], complete: bool, followed: float, quiet: bool) -> str:
    """The stated reading, as pre-registered in REPORT §4bj."""
    if not complete:
        return "not complete"
    if followed < FOLLOWED:
        return "the review's steps were not followed"
    m, (lo, hi) = c["against"]["mean"], c["against"]["ci95"]
    if lo > 0:
        said = "helps, at the bar" if m >= GAIN else "helps, under the bar"
        return said if quiet else f"{said}, and breaks more"
    return "no gain as large as the bar" if hi < GAIN else "inconclusive"


def score(write: bool) -> int:
    """Pass rates, the contrast and its reading, sub-agent use, harm on tests and controls, cost and time."""
    guard = run_guard.start()
    rows, planned, ts = list(kept().values()), calls(), tasks()
    broken = [t["id"] for t in ts if not t.get("needs_nothing")]
    controls = [t["id"] for t in ts if t.get("needs_nothing")]
    of = lambda a, ids: [r for r in rows if r["arm"] == a and r["id"] in ids]  # noqa: E731
    done = {a: len(of(a, broken)) for a in ARMS}
    plan = {a: sum(c["arm"] == a and c["id"] in broken for c in planned) for a in ARMS}
    complete = all(done[a] >= MIN_SHARE * plan[a] for a in ARMS)
    reviews = of("review", broken + controls)
    followed = sum(r["sub_agents"] > 0 for r in reviews) / len(reviews) if reviews else 0.0
    broke = {a: sum(not r["passed"] for r in of(a, controls)) + sum(bool(r["harm"]) for r in of(a, broken + controls))
             for a in ARMS}
    quiet = broke["review"] <= broke["none"] + EXTRA_HARM
    c = contrast(rows, broken)
    in_sample = [t["id"] for t in ts if t["id"] in broken and t.get("in_sample")]
    split = {name: contrast(rows, ids)["as_run"] for name, ids in
             (("in_sample", in_sample), ("out_of_sample", [i for i in broken if i not in in_sample]),
              *((f"set_{s}", [t["id"] for t in ts if t["set"] == s and t["id"] in broken]) for s in SETS)) if ids}
    checked = of("review", broken)
    out = {"section": "4bj", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "inputs": inputs(),
           "model": MODEL, "effort": EFFORT, "sessions": len(rows), "of": len(planned),
           "done_per_arm": done, "planned_per_arm": plan,
           "pass_rate": {a: round(mean(per_task(rows, a, broken, None).values()), 3) for a in ARMS},
           "per_task": {a: per_task(rows, a, broken, None) for a in ARMS},
           "contrast": c, "reading": reading(c, complete, followed, quiet),
           "review_sessions_that_started_a_sub_agent": round(followed, 3),
           "sub_agents_median": median(r["sub_agents"] for r in reviews) if reviews else None,
           "right_lesson_handed_to_a_sub_agent": round(mean(r["right_checked"] for r in checked), 3) if checked else None,
           "pass_rate_when_handed_and_not": {
               k: round(mean(r["passed"] for r in checked if r["right_checked"] is v), 3)
               for k, v in (("handed", True), ("not_handed", False)) if any(r["right_checked"] is v for r in checked)},
           "sessions_that_broke_something": broke, "quiet": quiet,
           "controls_broken": {a: sum(not r["passed"] for r in of(a, controls)) for a in ARMS},
           "controls_sessions": {a: len(of(a, controls)) for a in ARMS},
           "sessions_with_harm": {a: sum(bool(r["harm"]) for r in rows if r["arm"] == a) for a in ARMS},
           "sessions_harm_unknown": {a: sum(r.get("harm") is None for r in rows if r["arm"] == a) for a in ARMS},
           "edited": {a: sum(r["edited"] for r in of(a, broken)) for a in ARMS},
           "not_read": split,
           "usd_per_session": {a: round(mean(r["usd"] for r in rows if r["arm"] == a), 3) for a in ARMS
                               if any(r["arm"] == a for r in rows)},
           "median_seconds": {a: median(r["seconds"] for r in rows if r["arm"] == a) for a in ARMS
                              if any(r["arm"] == a for r in rows)},
           "api_priced_usd": round(sum(r["usd"] for r in rows), 2),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "rows": [{k: r.get(k) for k in ("id", "pr", "set", "arm", "rep", "passed", "grader_exit", "edited", "changed",
                                            "harm", "sub_agents", "right_checked", "seconds", "usd", "effort", "models",
                                            "room", "summary")} for r in rows]}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("rows", "per_task")}, indent=1))
    if write:
        dest = REPO / "evals" / "results" / f"review-graded-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0 if len(rows) == len(planned) else 2


def main() -> int:
    """build, check, run or score."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["build", "check", "run", "score"])
    ap.add_argument("--store", type=Path, default=STORE, help="the store to copy for build (default: this checkout's)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    if a.step == "build":
        return build(a.store, a.write)
    if a.step == "check":
        return check(a.receipt)
    return run(a.limit) if a.step == "run" else score(a.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
