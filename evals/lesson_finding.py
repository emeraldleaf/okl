"""REPORT §4bl, exploratory: cheap proxies for finding the right lesson, on §4bj's 43 graded broken tasks.

Each call is one prompt answered once, with no tools, so the whole set runs in about an hour instead of a
day of review sessions (docs/EVALUATION.md, "When a full run is needed"). It decides what is worth
building, not a default: none of its figures says what a review session would do.

- **Pick.** The review's list of lessons and the change's diff; pick N lessons the change most likely
  breaks: 10, today's step, and 30, a set wide enough to check with a cheaper model (#456). Reach: the
  right lesson is in the set.
- **Check.** One lesson, the diff, and the changed files as they are after it; does the change break the
  lesson? Three checkers: today's question on Sonnet; the same with a step that lists every path the
  lesson's rule covers, on Sonnet; and that on Haiku. Each on the right lesson, and on one decoy per task:
  a lesson §4bj's review handed a sub-agent for that task, not the right one (or, where none was handed,
  one drawn from the list). A decoy has no grader, so its "breaks" rate bounds false alarms from above.

    python3 evals/lesson_finding.py run [--limit N]
    python3 evals/lesson_finding.py score [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import default_read as dr
import replay_turn as rt
import review_graded as g
import review_graded_diagnose as diag
import run_guard
import sandbox as sb

from okl import core

REPO = g.REPO
OUT = REPO / "evals" / "bench" / "private" / "realwork" / "lesson-finding.jsonl"
PICKS = (10, 30)
CHECKERS = {"sonnet-ask": ("sonnet", False), "sonnet-paths": ("sonnet", True), "haiku-paths": ("haiku", True)}
EFFORT, WORKERS, TIMEOUT, STOP_AFTER_EMPTY, SEED = "medium", 3, 600, 3, 4651
DIFF_CHARS, FILE_CHARS, FILES_CHARS = 60_000, 12_000, 40_000
ARGV = ["claude", "-p", "--model", "{model}", "--output-format", "json", "--restricted", "--strict-mcp-config",
        "--tools", ""]

PICK = """You just wrote the change below. This repository keeps lessons: what went wrong before, and what to do instead. They are listed after the change, one line each; any that govern a file the change touched come first.

1. {step1}
2. Pick the {n} lessons this change is most likely to break: the ones about something the code does.

End your answer with one line of JSON and nothing after it: {{"picked": ["<id>", ...]}}, with exactly {n} ids from the list.

The change:
```diff
{diff}
```

{lessons}
"""

PATHS = ("Before you answer, list every path the lesson's rule covers: each entry point that does what the lesson "
         "is about, each error and fallback path, and existing code whose behaviour this change alters or makes "
         "reachable. Then check each path against the lesson, not only the lines the change added.\n")

CHECK = """Below are one of this repository's lessons, a change, and the files the change touched as they are after it. Question: does this change break this lesson? If the lesson has no bearing on this change, say so.
{paths}
End your answer with one line of JSON and nothing after it: {{"breaks": true}} or {{"breaks": false}}.

The lesson:
{lesson}

The change:
```diff
{diff}
```

The changed files after the change:
{files}
"""


def tasks() -> list[dict[str, Any]]:
    """The 43 graded broken tasks; the five controls have no right lesson to find."""
    return [t for t in g.tasks() if not t.get("needs_nothing")]


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} more characters cut]\n"


def diff(task: dict[str, Any]) -> str:
    """The change, base to frozen commit, cut to a size."""
    return _cut(g.o.git("diff", task["base"], task["frozen"]), DIFF_CHARS)


def changed_after(task: dict[str, Any]) -> str:
    """The changed files' text at the frozen commit, each and all cut to a size, deleted ones left out."""
    out, size = [], 0
    for path in dr.changed_files(g.o.git("diff", task["base"], task["frozen"])):
        try:
            text = g.o.git("show", f"{task['frozen']}:{path}")
        except Exception:  # noqa: BLE001, S112  # the change deleted it: nothing to show after
            continue
        block = f"--- {path}\n{_cut(text, FILE_CHARS)}"
        if size + len(block) > FILES_CHARS:
            out.append(f"--- {path}\n[left out: the changed files passed {FILES_CHARS} characters]")
            continue
        out.append(block)
        size += len(block)
    return "\n".join(out) or "(none)"


def lessons_section(task: dict[str, Any]) -> str:
    """The review's own lesson lines, as §4bj's REVIEW.md held them for this task."""
    text = (g.BUILT / task["id"] / "REVIEW.md").read_text()
    return text[text.index("### "):]


def lesson_text(task: dict[str, Any], lesson: str) -> str:
    """A lesson's full text as §4bj's review gave it for this task, redactions applied."""
    return (g.BUILT / task["id"] / "lessons" / f"{lesson.replace('/', '_')}.md").read_text()


def decoy(task: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """The lesson §4bj's review handed a sub-agent most often for this task, not the right one; where none
    was, one drawn, seeded, from the review's list."""
    listed = diag.LISTED.findall((g.BUILT / task["id"] / "REVIEW.md").read_text())
    handed: Counter[str] = Counter()
    for row in rows:
        folder = diag._room(row)
        if folder is None:
            continue
        for main in folder.glob("*.jsonl"):
            agents = [p.get("input") for p in diag._parts(diag._events(main), "assistant")
                      if p.get("type") == "tool_use" and p.get("name") in ("Agent", "Task")]
            blob = json.dumps(agents)
            handed.update(i for i in listed if i != task["lesson"] and any(n in blob for n in diag._names(i)))
    if handed:
        return sorted(handed.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    rng = random.Random(f"{SEED}-{task['id']}")  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return rng.choice(sorted(i for i in listed if i != task["lesson"]))


def calls() -> list[dict[str, Any]]:
    """Every call: two picks and, for the right lesson and the decoy, three checkers, per task; seeded order."""
    review = {}
    for r in g.kept().values():
        if r["arm"] == "review":
            review.setdefault(r["id"], []).append(r)
    out = []
    for t in tasks():
        out += [{"id": t["id"], "kind": "pick", "variant": f"n{n}", "n": n} for n in PICKS]
        for role, lesson in (("right", t["lesson"]), ("decoy", decoy(t, review.get(t["id"], [])))):
            out += [{"id": t["id"], "kind": "check", "variant": v, "role": role, "lesson": lesson} for v in CHECKERS]
    random.Random(SEED).shuffle(out)  # noqa: S311  # NOSONAR - seeded, reproducible on purpose
    return out


def ident(c: dict[str, Any]) -> tuple[str, str, str, str]:
    """What makes a call one: its task, kind, variant and role."""
    return c["id"], c["kind"], c["variant"], c.get("role", "")


def prompt(call: dict[str, Any], task: dict[str, Any]) -> str:
    """The one prompt a call sends."""
    if call["kind"] == "pick":
        return PICK.format(step1=core.REVIEW_STEPS[0], n=call["n"], diff=diff(task), lessons=lessons_section(task))
    return CHECK.format(paths=PATHS if CHECKERS[call["variant"]][1] else "", lesson=lesson_text(task, call["lesson"]),
                        diff=diff(task), files=changed_after(task))


def picked(text: str) -> list[str] | None:
    """The ids of the last JSON object in `text` that carries "picked"."""
    found = None
    for m in re.finditer(r"\{[^{}]*\"picked\"[^{}]*\}", text):
        try:
            got = json.loads(m.group(0)).get("picked")
        except ValueError:
            continue
        if isinstance(got, list):
            found = [str(i) for i in got]
    return found


def one(call: dict[str, Any], task: dict[str, Any], room: Path) -> dict[str, Any]:
    """One call, and its row: the ids picked or the answer given."""
    model = "sonnet" if call["kind"] == "pick" else CHECKERS[call["variant"]][0]
    argv = [a.replace("{model}", model) for a in ARGV]
    text = prompt(call, task)
    got = sb.ask(argv, text, model=model, effort=EFFORT, timeout=TIMEOUT, cwd=room)
    row = {**call, "model": model, "effort": EFFORT, "prompt_sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
           "models": got.get("models"), "usd": got.get("cost_usd") or 0.0, "error": got.get("error")}
    reply = got.get("result") or ""
    if call["kind"] == "pick":
        ids = picked(reply)
        row.update(picked=ids, reached=None if ids is None else task["lesson"] in ids)
    else:
        answer = dr.answer_in(reply)
        row["breaks"] = answer.get("breaks") if answer and isinstance(answer.get("breaks"), bool) else None
    row["said"] = reply[-400:]
    return row


def run(limit: int | None) -> int:
    """Every call not yet answered, three at a time; stops when three in a row give no answer."""
    done = {ident(json.loads(line)) for line in OUT.read_text().splitlines()} if OUT.exists() else set()
    todo = [c for c in calls() if ident(c) not in done][:limit]
    by_id = {t["id"]: t for t in tasks()}
    print(f"{len(todo)} of {len(calls())} calls to run", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with tempfile.TemporaryDirectory(prefix="okl-4bl-") as room, ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(one, c, by_id[c["id"]], Path(room)): c for c in todo}
        for n, f in enumerate(as_completed(futures), 1):
            row = f.result()
            usable = not row["error"] and (row.get("picked") is not None or row.get("breaks") is not None)
            empty = 0 if usable else empty + 1
            if usable:
                with OUT.open("a") as out:
                    out.write(json.dumps(row) + "\n")
            print(f"  [{n}/{len(todo)}] {row['id']} {row['kind']} {row['variant']} {row.get('role', '')}: "
                  f"{row.get('reached', row.get('breaks'))}{' ERROR ' + str(row['error'])[:80] if row['error'] else ''}",
                  flush=True)
            if empty >= STOP_AFTER_EMPTY:
                print("three calls in a row gave no answer: stopping (a usage limit looks like this)")
                for other in futures:
                    other.cancel()
                return 2
    return 0


def _rate(rows: list[dict[str, Any]], key: str, ids: list[str]) -> dict[str, float]:
    """Each task's value of `key` (a bool), so the tasks are the unit."""
    got = {r["id"]: float(bool(r[key])) for r in rows if r.get(key) is not None}
    return {i: got[i] for i in ids if i in got}


def _paired(a: dict[str, float], b: dict[str, float], seed: str) -> dict[str, Any]:
    both = sorted(set(a) & set(b))
    diffs = [a[i] - b[i] for i in both]
    return {"tasks": len(both), "mean": round(mean(diffs), 3) if diffs else None,
            "ci95": rt.interval(diffs, 0.95, seed) if diffs else None}


def _joined(reach: dict[str, dict[str, float]], said: dict[tuple[str, str], dict[str, float]]) -> dict[str, dict]:
    """Each pipeline's per-task catch: picked, then flagged by its checker (both, for a cheap screen and a
    confirming check), over the tasks where every part answered."""
    pipelines = {"pick 10, sonnet-ask (today)": ("n10", ("sonnet-ask",)),
                 "pick 10, sonnet-paths": ("n10", ("sonnet-paths",)),
                 "pick 30, sonnet-paths": ("n30", ("sonnet-paths",)),
                 "pick 30, haiku-paths": ("n30", ("haiku-paths",)),
                 "pick 30, haiku-paths screen then sonnet-paths": ("n30", ("haiku-paths", "sonnet-paths"))}
    out = {}
    for name, (pick, checkers) in pipelines.items():
        parts = [reach[pick], *(said[(c, "right")] for c in checkers)]
        common = set.intersection(*(set(x) for x in parts))
        out[name] = {i: float(all(x[i] for x in parts)) for i in sorted(common)}
    return out


def score(write: bool) -> int:
    """Reach per pick size, "breaks" per checker on the right lesson and the decoy, paired by task."""
    guard = run_guard.start()
    rows = [json.loads(line) for line in OUT.read_text().splitlines()] if OUT.exists() else []
    ids = [t["id"] for t in tasks()]
    pick = {v: [r for r in rows if r["kind"] == "pick" and r["variant"] == v] for v in (f"n{n}" for n in PICKS)}
    check = {(v, role): [r for r in rows if r["kind"] == "check" and r["variant"] == v and r["role"] == role]
             for v in CHECKERS for role in ("right", "decoy")}
    reach = {v: _rate(rs, "reached", ids) for v, rs in pick.items()}
    said = {k: _rate(rs, "breaks", ids) for k, rs in check.items()}
    out = {
        "section": "4bl", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "inputs": g.inputs(),
        "calls": len(rows), "of": len(calls()), "effort": EFFORT,
        "models": sorted({m for r in rows for m in r.get("models") or []}),
        "reach": {v: {"tasks": len(r), "rate": round(mean(r.values()), 3) if r else None} for v, r in reach.items()},
        "reach_n30_minus_n10": _paired(reach["n30"], reach["n10"], "4bl-reach"),
        "said_breaks": {f"{v} {role}": {"tasks": len(r), "rate": round(mean(r.values()), 3) if r else None}
                        for (v, role), r in said.items()},
        "paths_minus_ask_on_right": _paired(said[("sonnet-paths", "right")], said[("sonnet-ask", "right")], "4bl-p"),
        "paths_minus_ask_on_decoy": _paired(said[("sonnet-paths", "decoy")], said[("sonnet-ask", "decoy")], "4bl-pd"),
        "haiku_minus_sonnet_on_right": _paired(said[("haiku-paths", "right")], said[("sonnet-paths", "right")],
                                               "4bl-h"),
        "haiku_minus_sonnet_on_decoy": _paired(said[("haiku-paths", "decoy")], said[("sonnet-paths", "decoy")],
                                               "4bl-hd"),
        # Per task: the pick reaches the right lesson AND the checker says the change breaks it, the two
        # stages of a review joined, so a wider pick gains only where its checker would flag what it adds.
        "pick_then_check": {name: {"tasks": len(c), "rate": round(mean(c.values()), 3) if c else None}
                            for name, c in _joined(reach, said).items()},
        "usd_per_call": {k: round(mean(r["usd"] for r in rs), 4) for k, rs in
                         {**{f"pick {v}": rs for v, rs in pick.items()},
                          **{f"check {v}": [r for (vv, _), rr in check.items() if vv == v for r in rr]
                             for v in CHECKERS}}.items() if rs},
        "api_priced_usd": round(sum(r["usd"] for r in rows), 2),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rows": [{k: r.get(k) for k in ("id", "kind", "variant", "role", "lesson", "n", "model", "models", "effort",
                                        "prompt_sha256", "picked", "reached", "breaks", "usd")} for r in rows],
    }
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if write:
        dest = REPO / "evals" / "results" / f"lesson-finding-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0 if len(rows) == len(calls()) else 2


def main() -> int:
    """run or score."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["run", "score"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return run(a.limit) if a.step == "run" else score(a.receipt)


if __name__ == "__main__":
    sys.exit(main())
