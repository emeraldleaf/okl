#!/usr/bin/env python3
"""REPORT §4aq: the revised review with the repository to read, on 50 pull requests no review has read.

The steps run in order, and each refuses until the one before it is complete, so the key is finished
before any review exists for these tasks:

    python3 evals/review_repo.py status      # how many pull requests are in the pool
    python3 evals/review_repo.py freeze      # freeze 50, in the fixed draw order
    python3 evals/review_repo.py key         # Opus: labels, then each lesson's state with the repository to read
    python3 evals/review_repo.py run         # Sonnet: the review of §4ap, then the repository read for each "ask"
    python3 evals/review_repo.py judge       # Opus: is each raise true, and would a maintainer act on it
    python3 evals/review_repo.py score [--receipt]

`--sandbox DIR` keeps everything in DIR, and `freeze --prs 17,30` picks pull requests there: a plumbing
check on tasks already read, whose output is never cited. Answers land in evals/bench/private/realwork/
as each call returns, so a rerun asks only for what is missing. Nothing is posted on any pull request.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import os
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_arms as ba
import lesson_review as lr
import realwork_label as rl
import realwork_reach as rr
import realwork_tasks as rt
import review_action as ra

POOL_UNTIL, N_TASKS = "2026-11-08T00:23:00Z", 50   # §4al's pool, as it stood when its tasks were frozen (REPORT §4aq's amendment)
FIRST_PROMPT = "03a44686243e047b"   # §4ap's first pass, unchanged
W = SimpleNamespace(home=lr.PRIVATE, tasks=rr.REPO / "evals" / "realwork" / "tasks-4aq.jsonl", store=lr.PRIVATE / "store-4aq.db")
LABELS, STATES, FIRST, USAGE, SETTLED, VERDICTS, DECOYS = ("4aq-labels.jsonl", "4aq-states.jsonl", "4aq-first.jsonl", "4aq-usage.jsonl",
                                                          "4aq-settled.jsonl", "4aq-verdicts.jsonl", "4aq-decoys.json")
READ_ONLY = ["--output-format", "json", "--restricted", "--strict-mcp-config", "--tools", "Read,Grep,Glob"]
SONNET_READS, OPUS_READS = ["claude", "-p", "--model", "sonnet", *READ_ONLY], ["claude", "-p", "--model", "opus", *READ_ONLY]
ENV = {**os.environ, "OKL_BRIEFING_LOG": "0"}
AGENT_FILES = (".claude", ".cursor", ".mcp.json", "CLAUDE.md", "AGENTS.md")   # the copy must not brief or instruct the model
ACTION, RAISED_AFTER, CHANGE_FILE = ("not_followed", "check"), ("gap", "ask"), "CHANGE.diff"
WORKERS, TOOL_TIMEOUT, TOOL_BATCH, DECOY_SHARE, DECOY_VOID = 3, 900, 10, 0.1, 0.2
REACH_BAR, ACT_BAR, FALSE_BAR, RAISED_BAR = 0.70, 0.50, 5, 10
_usage_lock = threading.Lock()

KEY_PROMPT = """A team keeps lessons: rules, past defects and decisions it learned. Below is a pull request and some of the team's lessons. Your working directory is a read-only copy of the repository with this change applied.

TITLE: {title}

ISSUE:
{issues}

FILES CHANGED:
{files}

CHANGE:
{change}

LESSONS:
{lessons}

For each lesson, look at the change and at whatever else in the repository the lesson depends on, then say what state the change as written is in:
- "followed": the change already does what the lesson asks, or already avoids what it warns of, everywhere the lesson covers. A reviewer who knew the lesson would have nothing to ask for because of it.
- "not_followed": the change does what the lesson warns against, or leaves out something the lesson asks for, at some place the lesson covers. A reviewer who knew the lesson would ask for a change.
- "check": whether it holds depends on something outside the repository (how it merges, a live service, another branch), so a reviewer who knew the lesson would ask the author to confirm it.
- "unclear": you cannot tell, or you do not think this lesson bears on the change.

Answer with one JSON array and nothing else, one object per lesson, every lesson exactly once: [{{"id": "<lesson id>", "state": "followed|not_followed|check|unclear", "why": "<one short sentence, naming the file where you can>"}}]"""

SETTLE_PROMPT = """A first reader checked this pull request against what a team has written down. For each item below they said that whether it is met depends on something the diff does not show.

PULL REQUEST: {title}

WHAT IT WAS FOR:
{issues}

FILES THE WHOLE PULL REQUEST CHANGES:
{files}

THE DIFF (part {part} of {parts}):
{change}

THE ITEMS, WITH WHAT THE FIRST READER TOLD THE AUTHOR:
{items}

Your working directory is a read-only copy of the repository with this change applied. Use your tools to look up what each item depends on, then answer with one word:
- "gap": you looked, and the item is not met. Say where in to_author.
- "met": you looked, and it is met, or it does not apply to what this change does.
- "ask": you looked, and it depends on something outside the repository (how it merges, a live service, another branch), so the author has to confirm it.

Reply with one JSON array and nothing else, one object for every item: [{{"id": "<the id in square brackets>", "found": "<what you looked at and found>", "answer": "gap|met|ask", "to_author": "<for gap or ask, one sentence; otherwise empty>"}}]"""

JUDGE_PROMPT = """Someone reviewed a pull request against what a team has written down and raised each item below, with what they told the author. Your working directory is a read-only copy of the repository with this change applied.

TITLE: {title}

ISSUE:
{issues}

FILES CHANGED:
{files}

CHANGE:
{change}

THE RAISES:
{items}

Check each raise against the change and the repository, then answer with one word:
- "act": what it says is true of this change, and a maintainer who read the item would act on it.
- "minor": what it says is true of this change, but a maintainer could reasonably leave it.
- "false": what it says is not true of this change, or the item does not bear on what this change does.

Answer with one JSON array and nothing else, one object for every item: [{{"id": "<the id in square brackets>", "checked": "<what you looked at and found>", "answer": "act|minor|false"}}]"""


def sha(text: str) -> str:
    """The short hash a prompt is known by."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


PROMPTS = {"states": sha(KEY_PROMPT), "settle": sha(SETTLE_PROMPT), "judge": sha(JUDGE_PROMPT), "first": FIRST_PROMPT}


def eligible() -> list[dict]:
    """The pull requests §4al's draw could have taken and did not, none by a bot, in the fixed draw order."""
    out = subprocess.run(["gh", "pr", "list", "-R", rt.GH_REPO, "--state", "merged", "--limit", "500", "--json",
                          "number,createdAt,mergedAt,title,body,mergeCommit,author"], capture_output=True, text=True, check=True).stdout
    read = {json.loads(line)["pr"] for line in rr.TASKS.read_text().splitlines() if line.strip()}
    prs = [p for p in json.loads(out) if p["createdAt"][:10] >= rt.SINCE and p["mergedAt"] <= POOL_UNTIL
           and p["number"] not in read and not (p.get("author") or {}).get("is_bot")]
    return sorted(prs, key=lambda p: sha(f"4aq:{p['number']}"))


def snapshot() -> str:
    """Copy this machine's store beside the answers; its sha256."""
    W.store.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(rr.REPO / ".okl" / "okl.db") as live, sqlite3.connect(W.store) as copy:
        live.backup(copy)
    return ba.sha256(W.store)


def freeze(chosen: list[int] | None) -> int:
    """Freeze the first N_TASKS eligible pull requests (or, in a sandbox, `chosen`) and write them."""
    subprocess.run(["git", "-C", str(rr.REPO), "fetch", "-q", "origin"], check=True)
    if chosen is not None and W.home == lr.PRIVATE:
        sys.exit("--prs is for a --sandbox only")
    pool = eligible() if chosen is None else None
    if chosen is None and len(pool) < N_TASKS:
        sys.exit(f"{len(pool)} of {N_TASKS} eligible pull requests have merged; nothing frozen")
    if pool is None:
        all_prs = json.loads(subprocess.run(["gh", "pr", "list", "-R", rt.GH_REPO, "--state", "merged", "--limit", "500", "--json",
                                             "number,createdAt,mergedAt,title,body,mergeCommit,author"], capture_output=True, text=True, check=True).stdout)
        pool = [p for p in all_prs if p["number"] in chosen]
    digest = snapshot()
    tasks, skipped, leaks = [], [], []
    wanted = len(chosen) if chosen is not None else N_TASKS
    for p in pool:
        if len(tasks) == wanted:
            break
        try:
            pr, _ = rt.intake.fetch(p["number"], rt.GH_REPO)
        except rt.intake.IntakeError as e:
            skipped.append({"pr": p["number"], "why": f"gh: {e}"})
            continue
        got = rt.freeze_task(p, pr, "review" if any(t.get("isResolved") for t in pr["reviewThreads"]["nodes"]) else "none", W.store)
        if "task" in got:
            tasks.append(got["task"])
        elif "leak" in got:
            leaks.append({"pr": p["number"], "names": got["leak"]})
        else:
            skipped.append({"pr": p["number"], "why": got["skip"]})
    if len(tasks) < wanted:
        sys.exit(f"only {len(tasks)} of {wanted} could be frozen (skipped {skipped}, leaks {leaks}); nothing written")
    W.tasks.parent.mkdir(parents=True, exist_ok=True)
    W.tasks.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    print(json.dumps({"frozen": len(tasks), "first": tasks[0]["pr"], "last": tasks[-1]["pr"], "skipped": skipped, "leaks": leaks, "store_sha256": digest}, indent=1))
    return 0


def load_tasks() -> list[dict]:
    """The frozen tasks."""
    if not W.tasks.exists():
        sys.exit("no frozen tasks yet: run freeze")
    return [json.loads(line) for line in W.tasks.read_text().splitlines() if line.strip()]


@functools.cache
def texts() -> dict[str, str]:
    """Each lesson's text, from this test's snapshot."""
    return rl.lesson_text(W.store)


def rows_of(name: str) -> list[dict]:
    """The rows kept in one answers file."""
    path = W.home / name
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def keyed(name: str) -> dict[tuple[int, str], dict]:
    """One answers file by (pull request, lesson)."""
    return {(r["pr"], r["lesson"]): r for r in rows_of(name)}


def first_answers() -> dict[tuple[int, int, str], dict]:
    """The first pass's answers by (pull request, part, lesson)."""
    return {(r["pr"], r["part"], r["lesson"]): r for r in rows_of(FIRST) if r.get("prompt") == FIRST_PROMPT}


def worst_row(answers: dict[tuple[int, int, str], dict], task: dict, lesson: str) -> dict | None:
    """The answer asking most of the author across the task's parts."""
    got = [answers[(task["pr"], p, lesson)] for p in range(len(ra.parts_of(ra.whole(task)))) if (task["pr"], p, lesson) in answers]
    return max(got, key=lambda r: ra.WORDS.index(r["answer"]), default=None)


def issues_of(task: dict) -> str:
    """The issues a task closes, as the prompts show them."""
    return "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in task["issues"]) or "(none)"


def change_of(task: dict) -> str:
    """The change as a prompt shows it, or a pointer to the file holding it when it is too long to show."""
    diff = ra.whole(task)
    return diff if len(diff) <= rl.CUT else f"The change runs to {len(diff)} characters, too long to show here. It is in the file {CHANGE_FILE} in your working directory; read it through."


@contextlib.contextmanager
def checkout(task: dict) -> Iterator[Path]:
    """A copy of the repository at the task's commit: no history, no agent settings, the long change beside it."""
    room = Path(tempfile.mkdtemp(prefix="okl-4aq-"))
    try:
        archive = subprocess.run(["git", "-C", str(rr.REPO), "archive", task["commit"]], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(room)], input=archive, check=True)
        for name in AGENT_FILES:
            target = room / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        if len(ra.whole(task)) > rl.CUT:
            (room / CHANGE_FILE).write_text(ra.whole(task))
        yield room
    finally:
        shutil.rmtree(room, ignore_errors=True)


def note_usage(row: dict) -> None:
    """Keep what one call cost."""
    with _usage_lock, (W.home / USAGE).open("a") as usage:
        usage.write(json.dumps(row) + "\n")


def ask_with_repo(cmd: list[str], prompt: str, room: Path, *, pr: int, step: str) -> list:
    """The model's array for `prompt`, or nothing when it gave none (a later round asks again)."""
    start = time.monotonic()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TOOL_TIMEOUT, cwd=room, env=ENV)
    except subprocess.TimeoutExpired:
        note_usage({"pr": pr, "step": step, "seconds": TOOL_TIMEOUT, "error": "timeout"})
        return []
    try:
        reply = json.loads(p.stdout)
    except ValueError:
        return rl.last_array(p.stdout) or []
    u = reply.get("usage") or {}
    note_usage({"pr": pr, "step": step, "seconds": round(time.monotonic() - start, 1), "input": u.get("input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0), "output": u.get("output_tokens", 0), "api_priced_usd": reply.get("total_cost_usd", 0)})
    return rl.last_array(reply.get("result") or "") or []


def cost_of(prs: set[int]) -> dict:
    """Calls, tokens, model seconds and API-priced dollars of the review (not its key or judge), per pull request of `prs`."""
    by_pr: dict[int, dict] = {}
    for u in rows_of(USAGE):
        if u.get("step") in ("first", "settle") and u["pr"] in prs:   # #388 is settled for the ledger only
            p = by_pr.setdefault(u["pr"], {"calls": 0, "tokens": 0, "seconds": 0.0, "usd": 0.0})
            p["calls"] += 1
            p["tokens"] += u.get("input", 0) + u.get("cache_read", 0) + u.get("cache_write", 0) + u.get("output", 0)
            p["seconds"] += u.get("seconds", 0)
            p["usd"] += u.get("api_priced_usd", 0) or 0
    return {f"per_pr_median_{k}": round(statistics.median(p[k] for p in by_pr.values()), 2) for k in ("calls", "tokens", "seconds", "usd")} if by_pr else {}


def pick(got: list, ids: list[str], field: str, words: tuple[str, ...]) -> list[tuple[str, dict]]:
    """The items of a reply that name one of `ids` and give one of `words`."""
    out = []
    for item in got:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get(field) in words:
            lesson = lr.resolve(item["id"], ids)
            if lesson:
                out.append((lesson, item))
    return out


def pump(name: str, todo: Callable[[], list[tuple]], work: Callable[..., list[dict]]) -> None:
    """Run `work` over `todo()`, keeping each answer as it returns, until nothing is left or the rounds run out."""
    path = W.home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for attempt in range(lr.ROUNDS):
            jobs = todo()
            if not jobs:
                return
            print(f"{name} round {attempt + 1}: {len(jobs)} calls", file=sys.stderr, flush=True)
            for n, future in enumerate(as_completed([pool.submit(work, *j) for j in jobs]), 1):
                for row in future.result():
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                if n % 50 == 0:
                    print(f"  {n}/{len(jobs)}", file=sys.stderr, flush=True)


def batches(ids: list[str], size: int) -> list[list[str]]:
    """`ids` in calls of `size`."""
    return [ids[k:k + size] for k in range(0, len(ids), size)]


def label_jobs(tasks: list[dict], room: Path) -> list[tuple]:
    """Every lesson not yet labelled against its whole change."""
    done = {k for k, r in keyed(LABELS).items() if r.get("verdict")}
    return [(t, ids, texts(), ra.whole(t), room) for t in tasks
            for ids in batches([i for i in sorted(t["lessons"]) if (t["pr"], i) not in done and i in texts()], rl.BATCH)]


def state_batch(task: dict, ids: list[str]) -> list[dict]:
    """One call: the state the change is in for each of `ids`, with the repository to read."""
    prompt = KEY_PROMPT.format(title=task["title"], issues=issues_of(task), files="\n".join(task["paths"]), change=change_of(task),
                               lessons="\n\n".join(texts()[i] for i in ids))
    with checkout(task) as room:
        got = ask_with_repo(OPUS_READS, prompt, room, pr=task["pr"], step="key")
    return [{"pr": task["pr"], "lesson": i, "state": x["state"], "why": str(x.get("why", ""))[:300], "prompt": PROMPTS["states"]}
            for i, x in pick(got, ids, "state", (*ACTION, "followed", "unclear"))]


def key_gaps(tasks: list[dict]) -> list[str]:
    """What the key still lacks: an unlabelled pair, or a labelled needed or related pair with no state."""
    labels, states = keyed(LABELS), keyed(STATES)
    gaps = [f"#{t['pr']} {i}: no label" for t in tasks for i in t["lessons"] if i in texts() and not labels.get((t["pr"], i), {}).get("verdict")]
    return gaps + [f"#{k[0]} {k[1]}: no state" for k, r in labels.items() if r.get("verdict") in ("needed", "related") and k not in states]


def make_key() -> int:
    """Label every pair against the whole change, then give each needed or related pair its state."""
    tasks = load_tasks()
    by_pr = {t["pr"]: t for t in tasks}
    with tempfile.TemporaryDirectory(prefix="okl-4aq-") as tmp:
        pump(LABELS, lambda: label_jobs(tasks, Path(tmp)), rl.label_batch)

    def todo() -> list[tuple]:
        labels, done = keyed(LABELS), keyed(STATES)
        group = defaultdict(list)
        for (pr, i), r in labels.items():
            if r.get("verdict") in ("needed", "related") and (pr, i) not in done:
                group[pr].append(i)
        return [(by_pr[pr], ids) for pr, all_ids in group.items() for ids in batches(sorted(all_ids), TOOL_BATCH)]

    pump(STATES, todo, state_batch)
    gaps = key_gaps(tasks)
    print(json.dumps({"tasks": len(tasks), "labels": Counter(r.get("verdict") for r in keyed(LABELS).values()),
                      "states": Counter(r["state"] for r in keyed(STATES).values()), "gaps": gaps[:20]}))
    return 0 if not gaps else 2


def settle_batch(task: dict, part: int, ids: list[str], lesson_text: dict[str, str], told: dict[str, str]) -> list[dict]:
    """One call: each "ask" settled by reading the repository."""
    parts = ra.parts_of(ra.whole(task))
    prompt = SETTLE_PROMPT.format(title=task["title"], issues=issues_of(task), files="\n".join(task["paths"]), part=part + 1, parts=len(parts), change=parts[part],
                                  items="\n\n".join(f"{lesson_text[i]}\nTOLD TO THE AUTHOR: {told[i] or '(nothing)'}" for i in ids))
    with checkout(task) as room:
        got = ask_with_repo(SONNET_READS, prompt, room, pr=task["pr"], step="settle")
    return [{"pr": task["pr"], "lesson": i, "answer": x["answer"], "to_author": str(x.get("to_author") or "")[:lr.LINE_CUT], "found": str(x.get("found") or "")[:300], "prompt": PROMPTS["settle"]}
            for i, x in pick(got, ids, "answer", ("gap", "met", "ask"))]


def settle_jobs(tasks: list[dict], answers: dict[tuple[int, int, str], dict], lesson_text: dict[str, str]) -> list[tuple]:
    """Every "ask" not yet settled, grouped by the part of the change it was asked on."""
    done, jobs = keyed(SETTLED), []
    for t in tasks:
        group: dict[int, dict[str, str]] = defaultdict(dict)
        for i in sorted(t["lessons"]):
            row = worst_row(answers, t, i) if i in lesson_text else None
            if row and row["answer"] == "ask" and (t["pr"], i) not in done:
                group[row["part"]][i] = row.get("to_author", "")
        jobs += [(t, part, ids, lesson_text, told) for part, told in group.items() for ids in batches(sorted(told), TOOL_BATCH)]
    return jobs


def the_ledger_task() -> dict:
    """#388 as §4al froze it: the ledger's two lessons are checked there, on §4ap's first-pass answers."""
    return next(t for t in map(json.loads, rr.TASKS.read_text().splitlines()) if t["pr"] == ra.LEDGER_PR)


def first_call(job: dict, room: Path) -> list[dict]:
    """One first-pass call, unchanged from §4ap; its cost goes to the usage file."""
    rows, use = ra.one(job, texts(), room)
    note_usage({**use, "step": "first"})
    return rows


def run() -> int:
    """The review: §4ap's first pass, then the repository read for each "ask"; refuses until the key is complete."""
    if ra.PROMPT_SHA != FIRST_PROMPT:
        sys.exit(f"the first pass's prompt changed ({ra.PROMPT_SHA}); this is not the review that was pre-registered")
    tasks = load_tasks()
    gaps = key_gaps(tasks)
    if gaps:
        sys.exit(f"the answer key is not complete, so no review runs: {len(gaps)} gaps, first {gaps[0]}")
    with tempfile.TemporaryDirectory(prefix="okl-4aq-") as tmp:
        pump(FIRST, lambda: [(j, Path(tmp)) for j in ra.jobs_for(tasks, texts(), first_answers())], first_call)
    pump(SETTLED, lambda: settle_jobs(tasks, first_answers(), texts()), settle_batch)
    ledger_text = rl.lesson_text(rr.SNAPSHOT)
    pump(SETTLED, lambda: settle_jobs([the_ledger_task()], ra.load_answers(), ledger_text), settle_batch)
    missing = len(ra.jobs_for(tasks, texts(), first_answers())) + len(settle_jobs(tasks, first_answers(), texts()))
    print(json.dumps({"tasks": len(tasks), "first_pass_answers": len(first_answers()), "settled": Counter(r["answer"] for r in keyed(SETTLED).values()), "calls_still_missing": missing}))
    return 0 if not missing else 2


def raised_on(task: dict, answers: dict[tuple[int, int, str], dict], settled: dict[tuple[int, str], dict], lesson_text: dict[str, str]) -> dict[str, str]:
    """What the review raises on a task: each lesson, with what it tells the author."""
    out = {}
    for i in sorted(task["lessons"]):
        row = worst_row(answers, task, i) if i in lesson_text else None
        if row and row["answer"] == "gap":
            out[i] = row.get("to_author", "")
        elif row and row["answer"] == "ask":
            done = settled.get((task["pr"], i), {})
            if done.get("answer") in RAISED_AFTER:
                out[i] = done.get("to_author", "") or row.get("to_author", "")
    return out


def judge_batch(task: dict, items: list[tuple[str, str]]) -> list[dict]:
    """One call: the verdict on each raise, with the repository to read."""
    ids = [i for i, _ in items]
    prompt = JUDGE_PROMPT.format(title=task["title"], issues=issues_of(task), files="\n".join(task["paths"]), change=change_of(task),
                                 items="\n\n".join(f"{texts()[i]}\nTOLD TO THE AUTHOR: {told or '(nothing)'}" for i, told in items))
    with checkout(task) as room:
        got = ask_with_repo(OPUS_READS, prompt, room, pr=task["pr"], step="judge")
    return [{"pr": task["pr"], "lesson": i, "answer": x["answer"], "checked": str(x.get("checked") or "")[:300], "prompt": PROMPTS["judge"]}
            for i, x in pick(got, ids, "answer", ("act", "minor", "false"))]


def decoys_for(tasks: list[dict], raised: dict[int, dict[str, str]]) -> dict[str, dict[str, str]]:
    """About one raise in ten taken from another pull request, which should not hold here: kept once, so reruns agree."""
    path = W.home / DECOYS
    if path.exists():
        return json.loads(path.read_text())
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded draw, not a secret
    pool = [(pr, i, told) for pr, here in raised.items() for i, told in here.items()]
    out = {}
    for t in tasks:
        here = raised[t["pr"]]
        others = [x for x in pool if x[0] != t["pr"] and x[1] not in here and x[1] in t["lessons"]]
        rng.shuffle(others)  # NOSONAR - seeded, reproducible on purpose
        picked: dict[str, str] = {}
        for _, i, told in others:
            if len(picked) >= (max(1, round(len(here) * DECOY_SHARE)) if here else 0):
                break
            picked.setdefault(i, told)
        out[str(t["pr"])] = picked
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def judge() -> int:
    """Grade every raise and the decoys among them; refuses until the review is complete."""
    tasks = load_tasks()
    answers, settled = first_answers(), keyed(SETTLED)
    if ra.jobs_for(tasks, texts(), answers) or settle_jobs(tasks, answers, texts()):
        sys.exit("the review is not complete, so nothing is judged")
    raised = {t["pr"]: raised_on(t, answers, settled, texts()) for t in tasks}
    decoys = decoys_for(tasks, raised)
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded shuffle, not a secret

    def todo() -> list[tuple]:
        done, jobs = keyed(VERDICTS), []
        for t in tasks:
            items = [(i, told) for i, told in {**raised[t["pr"]], **decoys[str(t["pr"])]}.items() if (t["pr"], i) not in done]
            rng.shuffle(items)
            jobs += [(t, items[k:k + TOOL_BATCH]) for k in range(0, len(items), TOOL_BATCH)]
        return jobs

    pump(VERDICTS, todo, judge_batch)
    left = len(todo())
    print(json.dumps({"verdicts": Counter(r["answer"] for r in keyed(VERDICTS).values()), "calls_still_missing": left}))
    return 0 if not left else 2


def task_row(task: dict, raised: dict[str, str], labels: dict[tuple[int, str], dict], states: dict[tuple[int, str], dict], verdicts: dict[tuple[int, str], dict]) -> dict:
    """One task's scoring row, in the shape briefing_arms.tally reads."""
    pr = task["pr"]
    action = sorted(i for i in task["lessons"] if labels.get((pr, i), {}).get("verdict") in ("needed", "related") and states.get((pr, i), {}).get("state") in ACTION)
    grades = Counter(verdicts.get((pr, i), {}).get("answer", "unjudged") for i in raised)
    return {"pr": pr, "needed": action, "named": {"base": [], "review": sorted(raised)}, "missed": sorted(set(action) - set(raised)), "grades": dict(grades),
            "confirmed": sorted(set(action) & set(raised))}


def act_share(rows: list[dict], rng: random.Random) -> tuple[float, list[float]]:
    """The share of raises judged worth acting on, with a bootstrap over the tasks that raised anything."""
    pairs = [(r["grades"].get("act", 0), sum(r["grades"].values())) for r in rows if r["grades"]]
    share = sum(a for a, _ in pairs) / max(1, sum(n for _, n in pairs))
    boots = []
    for _ in range(ba.BOOT):
        s = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        boots.append(sum(a for a, _ in s) / max(1, sum(n for _, n in s)))
    boots.sort()
    return round(share, 3), [round(boots[int(0.025 * ba.BOOT)], 3), round(boots[int(0.975 * ba.BOOT) - 1], 3)]


def ledger_raised() -> dict[str, bool]:
    """Whether the review raises each ledger lesson on #388, on §4ap's first-pass answers and this test's settling."""
    task, text = the_ledger_task(), rl.lesson_text(rr.SNAPSHOT)
    here = raised_on(task, ra.load_answers(), keyed(SETTLED), text)
    return {i: i in here for i in (json.loads(line)["lesson"] for line in lr.LEDGER.read_text().splitlines() if line.strip())}


def score(write: bool) -> int:
    """Score the run against the key and the judge; write the receipt with `write`."""
    tasks = load_tasks()
    labels, states, verdicts, answers, settled = keyed(LABELS), keyed(STATES), keyed(VERDICTS), first_answers(), keyed(SETTLED)
    raised = {t["pr"]: raised_on(t, answers, settled, texts()) for t in tasks}
    decoys = json.loads((W.home / DECOYS).read_text()) if (W.home / DECOYS).exists() else {}
    unjudged = sum(1 for pr, here in raised.items() for i in here if (pr, i) not in verdicts)
    usable = not (key_gaps(tasks) or ra.jobs_for(tasks, texts(), answers) or settle_jobs(tasks, answers, texts()) or unjudged)
    rows = [task_row(t, raised[t["pr"]], labels, states, verdicts) for t in tasks]
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    v = ba.tally(rows, "review", {}, rng)   # with an empty base, the gain is the reach and its interval the reach's
    share, share_ci = act_share(rows, rng)
    decoy_grades = Counter(verdicts.get((int(pr), i), {}).get("answer", "unjudged") for pr, here in decoys.items() for i in here)
    decoy_acted = decoy_grades["act"] / max(1, sum(decoy_grades.values()))
    n_raised, n_false = [len(r["named"]["review"]) for r in rows], [r["grades"].get("false", 0) for r in rows]
    ledger = ledger_raised()
    void = decoy_acted > DECOY_VOID
    holds = {"reach_lower_bound_at_least_70": v["gain_boot95"][0] >= REACH_BAR, "act_share_lower_bound_at_least_50": share_ci[0] >= ACT_BAR,
             "false_median_at_most_5": statistics.median(n_false) <= FALSE_BAR, "raised_median_at_most_10": statistics.median(n_raised) <= RAISED_BAR,
             "both_ledger_lessons_raised": all(ledger.values())}
    predictions = {"reach at least 70%": v["reach"] >= REACH_BAR, "at least half of the raises judged worth acting on": share >= ACT_BAR,
                   "raises at most 5 at the median task": statistics.median(n_raised) <= 5, "misses a lesson calling for action on more than a third of the tasks": v["failure_rate"] > 1 / 3}
    status = "RESULTS NOT USABLE: the judge passed too many decoys" if void else "model-judged, not yet audited" if usable else "INCOMPLETE"
    out = {"section": "4aq", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": rl.git("rev-parse", "HEAD").strip(), "status": status, "usable": usable and not void,
           "prompts": PROMPTS, "script_sha256": ba.sha256(Path(__file__)), "inputs": {"tasks_sha256": ba.sha256(W.tasks), "store_sha256": ba.sha256(W.store)},
           "result": {"tasks": v["tasks"], "tasks_with_action": v["tasks_with_needed"], "calling_for_action": v["needed"], "reach": v["reach"], "reach_boot95": v["gain_boot95"],
                      "tasks_missing": v["tasks_missing"], "failure_rate": v["failure_rate"], "failure_wilson95": v["failure_wilson95"],
                      "raised_median": statistics.median(n_raised), "raised_max": max(n_raised), "false_median": statistics.median(n_false),
                      "act_share": share, "act_share_boot95": share_ci, "grades": dict(sum((Counter(r["grades"]) for r in rows), Counter()))},
           "decoys": {"grades": dict(decoy_grades), "act_share": round(decoy_acted, 3), "void_above": DECOY_VOID}, "ledger_on_388": ledger, "cost": cost_of({t["pr"] for t in tasks}),
           "holds": {**holds, "all": all(holds.values()) and not void}, "predictions": predictions, "per_task": rows}
    print(status)
    print(json.dumps({k: out[k] for k in ("result", "decoys", "ledger_on_388", "cost", "holds", "predictions")}, indent=1))
    if write:
        path = rr.REPO / "evals" / "results" / f"review-repo-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(rr.REPO)}")
    return 0 if usable and not void else 2


def status() -> int:
    """How many pull requests are in the pool, and whether that is enough."""
    got = eligible()
    print(json.dumps({"in_pool": len(got), "needed": N_TASKS, "ready": len(got) >= N_TASKS, "merged_by": POOL_UNTIL}))
    return 0


def main() -> int:
    """Dispatch the step asked for."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sandbox", help="keep tasks and answers in this directory (a plumbing check; never cited)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "key", "run", "judge"):
        sub.add_parser(name)
    sub.add_parser("freeze").add_argument("--prs", help="comma-separated pull requests; sandbox only")
    sub.add_parser("score").add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    if args.sandbox:
        W.home = Path(args.sandbox)
        W.home.mkdir(parents=True, exist_ok=True)
        W.tasks, W.store = W.home / "tasks.jsonl", W.home / "store.db"
    if args.cmd == "freeze":
        return freeze([int(x) for x in args.prs.split(",")] if args.prs else None)
    if args.cmd == "score":
        return score(args.receipt)
    return {"status": status, "key": make_key, "run": run, "judge": judge}[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
