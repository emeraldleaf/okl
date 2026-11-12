#!/usr/bin/env python3
"""REPORT §4bc: can okl choose the lessons a change breaks better than a model picking from the list?

Today the review after writing has the agent read the change and pick ten lessons from every
lesson's one line: a list, the shape §4ax found weak, and about half the right lessons (§4ba). On the
58 past changes whose keys hold a broken lesson (§4al's and §4aq's tasks), this compares ways of
choosing, each as a ranked list of lessons:

  pick     Sonnet picks ten from every lesson's line, given the change (§4ba's picker, today's shape).
  chunk    each changed hunk is a query of its own to okl's search (full text and the static
           embedding, linear); the hunks' lists are fused.
  desc     a one-sentence description of each hunk (Haiku) is the query instead; fused.
  anchor   code names and paths in the change matched to the lessons that mention them, and the
           lessons whose files govern a changed path. No model.
  pool     the four fused, top POOL.
  screen   each pooled lesson asked on its own (Haiku): does this change do something this lesson is
           about? The yeses.

A hit is a lesson the key sorted broken. Result and data files are left out of every arm's view.

    python3 evals/pick_fix.py prep      # descriptions and picks, resumable
    python3 evals/pick_fix.py screen    # one call per pooled lesson, resumable
    python3 evals/pick_fix.py score [--receipt]
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
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import default_read as dr
import explain_search as es
import lesson_review as lr
import plan_reach as pr
import review_action as ra
import run_guard
from when_lines import last_object

from okl import core
from okl.store import Store

REPO = Path(__file__).resolve().parents[1]
PREP = lr.PRIVATE / "pick-fix-prep-4bc.jsonl"
SCREEN = lr.PRIVATE / "pick-fix-screen-4bc.jsonl"
HAIKU = ["claude", "-p", "--model", "haiku", "--output-format", "json", "--restricted", "--strict-mcp-config", "--tools", ""]
SONNET = [*pr.SONNET, "--tools", ""]
DATA = re.compile(r"(?:^(?:evals/results/|evals/bench/|evals/realwork/))|(?:\.(?:json|jsonl|txt|csv|svg|png|lock|db)$)")
MAX_CHUNKS, CHUNK_CUT, PICK_CUT, PER_CHUNK, POOL, K, RRF = 20, 1500, 40_000, 10, 30, 10, 60
GAIN, MAX_SET, MIN_COMPLETE = 0.15, 12, 52
DESC_PROMPT = """Below are numbered parts of one code change, each a diff hunk (+ added, - removed lines) with its file.

For each part, write one plain sentence saying what that code does: what it reads or writes (files, folders, databases, environment, network, output), what it calls, what it assumes, or how it fails. Name the mechanism, not the feature.

Answer with one JSON object mapping each part's number to its sentence, and nothing after it.

{parts}"""
SCREEN_PROMPT = """Below is what one code change does, one sentence per part, and the files it changes. Then one lesson a software team keeps.

Does this change do something this lesson is about, so the lesson bears on it? A lesson bears on a change when the change does what the lesson is about or touches what it governs, whether or not the change follows it.

Answer with one JSON object and nothing after it: {{"bears": true or false, "reason": "one short sentence"}}

## The change
Files: {files}
{sentences}

## The lesson
{lesson}"""
INSTRUMENT = hashlib.sha256((DESC_PROMPT + SCREEN_PROMPT + pr.PICK_PROMPT).encode()).hexdigest()[:16]


def cases() -> list[tuple[str, dict, set[str]]]:
    """Every past change whose key holds a broken lesson: (half, task, broken lessons)."""
    out = []
    for half in ("dev", "test"):
        key = es.key_of(half)
        for task in es.tasks_of(half):
            broken = {lesson for (p, lesson), c in key.items() if p == task["pr"] and c == "broken"}
            if broken:
                out.append((half, task, broken))
    return out


def chunks(diff: str) -> list[dict]:
    """The change's hunks outside result and data files, the MAX_CHUNKS largest, in diff order."""
    out = []
    for block in re.split(r"(?m)^diff --git ", diff)[1:]:
        path = block.split(" b/", 1)[-1].split("\n", 1)[0]
        if DATA.search(path):
            continue
        for hunk in re.split(r"(?m)^@@", block)[1:]:
            lines = [ln for ln in hunk.splitlines()[1:] if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
            text = "\n".join(lines)[:CHUNK_CUT]
            if text.strip():
                out.append({"file": path, "text": text})
    keep = sorted(range(len(out)), key=lambda i: -len(out[i]["text"]))[:MAX_CHUNKS]
    return [out[i] for i in sorted(keep)]


def view(diff: str) -> str:
    """The change as the picker reads it: result and data files left out, cut at PICK_CUT."""
    blocks = [b for b in re.split(r"(?m)^(?=diff --git )", diff) if b and not DATA.search(b.split(" b/", 1)[-1].split("\n", 1)[0])]
    return "".join(blocks)[:PICK_CUT]


def fuse(lists: list[list[str]]) -> list[str]:
    """Reciprocal-rank fusion of ranked lists."""
    score: dict[str, float] = defaultdict(float)
    for ranked in lists:
        for i, lesson in enumerate(ranked):
            score[lesson] += 1 / (RRF + i + 1)
    return sorted(score, key=lambda x: (-score[x], x))


NAME = re.compile(r"--[a-z][a-z-]{2,}|\b[A-Za-z_][A-Za-z0-9_]{4,}\b")


def anchors(parts: list[dict], texts: dict[str, str], governed: list[str]) -> list[str]:
    """Lessons that name a code name or path the change uses, weighted by how rare the name is
    among lessons, after the lessons whose files govern a changed path."""
    names = set()
    for part in parts:
        names.add(Path(part["file"]).name)
        for m in NAME.findall(part["text"]):
            if m.startswith("--") or "_" in m or m.isupper() or re.search(r"[a-z][A-Z]", m):
                names.add(m)
    lowered = {i: t.lower() for i, t in texts.items()}
    score: dict[str, float] = defaultdict(float)
    for name in names:
        n = name.lower()
        holders = [i for i, t in lowered.items() if n in t]
        if 0 < len(holders) <= max(3, len(texts) // 20):
            for i in holders:
                score[i] += 1 / len(holders)
    rest = sorted((i for i in score if i not in governed), key=lambda i: (-score[i], i))
    return [*governed, *rest]


SEARCH_LOCK = threading.Lock()


def search(db: Path, text: str, lessons: set[str]) -> list[str]:
    """okl's search, one at a time: the static embedding's tokenizer fails when two threads share it
    ("Already borrowed"), which stopped §4bc's first two runs before any row was kept."""
    with SEARCH_LOCK:
        return es.ranked(db, text, lessons, PER_CHUNK)


def ask(cmd: list[str], prompt: str, model: str) -> str | None:
    """One call's text, or None (a usage limit looks like this)."""
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900)
        reply = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return None
    return reply.get("result") or "" if any(model in m for m in reply.get("modelUsage") or {}) else None


def prep_one(half: str, task: dict) -> dict | None:
    """One change's descriptions and pick, and the search and anchor lists that need no model."""
    diff = ra.whole(task)
    parts = chunks(diff)
    with tempfile.TemporaryDirectory() as side:
        db = es.store_for(half, task, Path(side))
        lessons = set(task["lessons"])
        texts = {i: t for i, t in dr.full_text(db).items() if i in lessons}
        nodes = [n for n in Store(f"sqlite:///{db}").all_nodes() if n.id in lessons]
        changed = {b.split(" b/", 1)[-1].split("\n", 1)[0] for b in re.split(r"(?m)^diff --git ", diff)[1:]}
        governed = sorted(n.id for n in core.governing(nodes, "okl", changed))
        chunk_lists = [search(db, part["text"], lessons) for part in parts]
        body = "\n\n".join(f"[{i + 1}] {part['file']}\n{part['text']}" for i, part in enumerate(parts))
        raw = ask(HAIKU, DESC_PROMPT.format(parts=body), "haiku") if parts else "{}"
        obj = last_object(raw or "") or {}
        desc = {int(k): v for k, v in obj.items() if str(k).isdigit()}
        if parts and not desc:
            return None
        desc_lists = [search(db, s, lessons) for _, s in sorted(desc.items())]
    lines = es.lesson_lines(half, task)
    picked = pr.last_array(ask(SONNET, pr.PICK_PROMPT.format(kind=pr.KIND["diff"], k=K, change=view(diff), lessons="\n".join(lines)), "sonnet") or "")
    if not picked:
        return None
    known = {line.split(" | ", 1)[0] for line in lines}
    return {"half": half, "pr": task["pr"], "instrument": INSTRUMENT, "chunks": len(parts), "files": sorted(changed - {""}),
            "sentences": [s for _, s in sorted(desc.items())], "pick": [i for i in picked if i in known][:K],
            "chunk": fuse(chunk_lists), "desc": fuse(desc_lists), "anchor": anchors(parts, texts, governed), "governed": governed}


def kept(path: Path, keyfn: Callable[[dict], tuple]) -> dict:
    """Rows kept under this instrument."""
    if not path.exists():
        return {}
    return {keyfn(r): r for r in map(json.loads, path.read_text().splitlines()) if r.get("instrument") == INSTRUMENT}


def pool(row: dict) -> list[str]:
    """The four lists fused, top POOL."""
    return fuse([row["pick"], row["chunk"][:POOL], row["desc"][:POOL], row["anchor"][:POOL]])[:POOL]


def run_parallel(todo: list, fn: Callable[..., dict | None], sink_path: Path) -> int:
    """Run `fn` over `todo` a few at a time, keeping each result; stop when calls keep failing."""
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    empty = 0
    with sink_path.open("a") as sink, ThreadPoolExecutor(max_workers=4) as workers:
        futures = {workers.submit(fn, *item): item for item in todo}
        for f in as_completed(futures):
            row = f.result()
            if row:
                sink.write(json.dumps(row) + "\n"); sink.flush()
                empty = 0
                continue
            empty += 1
            if empty >= 8:
                print(f"stopped: {empty} calls in a row gave nothing", file=sys.stderr, flush=True)
                for other in futures:
                    other.cancel()
                return 2
    return 0


def prep() -> int:
    """Descriptions and picks for every change without them."""
    have = kept(PREP, lambda r: (r["half"], r["pr"]))
    todo = [(h, t) for h, t, _ in cases() if (h, t["pr"]) not in have]
    print(f"{len(todo)} of {len(cases())} changes to prepare (instrument {INSTRUMENT})", file=sys.stderr, flush=True)
    return run_parallel(todo, prep_one, PREP)


def screen_one(item: tuple[str, int, str, list[str], list[str], str]) -> dict | None:
    """One pooled lesson, asked on its own whether it bears on the change."""
    half, pr_, lesson, files, sentences, text = item
    prompt = SCREEN_PROMPT.format(files=", ".join(files[:40]), sentences="\n".join(f"- {s}" for s in sentences), lesson=text)
    raw = ask(HAIKU, prompt, "haiku")
    if raw is None:
        return None
    decoder, got = json.JSONDecoder(), None
    for i, ch in enumerate(raw):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(raw, i)
            except ValueError:
                continue
            if isinstance(obj, dict) and "bears" in obj:
                got = obj
    if got is None:
        return None
    return {"half": half, "pr": pr_, "lesson": lesson, "instrument": INSTRUMENT, "bears": bool(got.get("bears")), "reason": got.get("reason")}


def screen() -> int:
    """One call per pooled lesson without a verdict."""
    rows = kept(PREP, lambda r: (r["half"], r["pr"]))
    have = kept(SCREEN, lambda r: (r["half"], r["pr"], r["lesson"]))
    tasks = {(h, t["pr"]): t for h, t, _ in cases()}
    todo = []
    for (half, pr_), row in sorted(rows.items()):
        with tempfile.TemporaryDirectory() as side:
            texts = dr.full_text(es.store_for(half, tasks[(half, pr_)], Path(side)))
        todo += [((half, pr_, lesson, row["files"], row["sentences"], texts.get(lesson, "")),)
                 for lesson in pool(row) if (half, pr_, lesson) not in have]
    print(f"{len(todo)} pooled lessons to screen", file=sys.stderr, flush=True)
    return run_parallel(todo, screen_one, SCREEN)


def recall(found: list[str], broken: set[str]) -> float:
    """The share of a change's broken lessons a list holds."""
    return len(set(found) & broken) / len(broken)


def reading(rates: dict[str, float], screen_size: float, interval: list[float], complete: bool) -> str:
    """The new way of choosing works if the screened set finds clearly more broken lessons than
    today's pick of ten, and stays small enough to check one at a time."""
    if not complete:
        return "not complete"
    better = rates["screen"] - rates["pick"] >= GAIN and interval[0] > 0
    return "choosing improves" if better and screen_size <= MAX_SET else "choosing does not improve enough"


def score(write: bool) -> int:
    """Recall per arm, averaged over changes, with a paired bootstrap for screen against pick."""
    guard = run_guard.start()
    rows = kept(PREP, lambda r: (r["half"], r["pr"]))
    verdicts = kept(SCREEN, lambda r: (r["half"], r["pr"], r["lesson"]))
    per: list[dict] = []
    for half, task, broken in cases():
        row = rows.get((half, task["pr"]))
        if not row:
            continue
        pooled = pool(row)
        if not all((half, task["pr"], lesson) in verdicts for lesson in pooled):
            continue
        yes = [lesson for lesson in pooled if verdicts[(half, task["pr"], lesson)]["bears"]]
        per.append({"half": half, "pr": task["pr"], "broken": len(broken), "screen_size": len(yes),
                    "pick": recall(row["pick"], broken), "chunk": recall(row["chunk"][:K], broken), "desc": recall(row["desc"][:K], broken),
                    "anchor": recall(row["anchor"][:K], broken), "pool": recall(pooled, broken), "screen": recall(yes, broken)})
    arms = ("pick", "chunk", "desc", "anchor", "pool", "screen")
    rates = {a: round(mean(p[a] for p in per), 3) if per else 0.0 for a in arms}
    rng, draws = random.Random(4), []  # noqa: S311 - a seeded bootstrap
    for _ in range(2000):
        s = [per[rng.randrange(len(per))] for _ in per]
        draws.append(mean(p["screen"] for p in s) - mean(p["pick"] for p in s))
    draws.sort()
    interval = [round(draws[50], 3), round(draws[1949], 3)] if per else [0.0, 0.0]
    size = round(mean(p["screen_size"] for p in per), 1) if per else 0.0
    out = {"section": "4bc", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "instrument": INSTRUMENT, "changes": len(per), "of": len(cases()),
           "broken_lessons": sum(p["broken"] for p in per), "recall": rates, "screen_minus_pick": round(rates["screen"] - rates["pick"], 3),
           "interval": interval, "screen_set_mean": size, "reading": reading(rates, size, interval, len(per) >= MIN_COMPLETE),
           "by_half": {h: {a: round(mean(p[a] for p in per if p["half"] == h), 3) for a in arms} for h in ("dev", "test") if any(p["half"] == h for p in per)},
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "per_change": per}
    out = guard.stamp(out)
    print(json.dumps({k: v for k, v in out.items() if k != "per_change"}, indent=1))
    if write:
        dest = REPO / "evals" / "results" / f"pick-fix-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0 if len(per) == len(cases()) else 2


def main() -> int:
    """prep, screen or score."""
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prep", "screen", "score"])
    ap.add_argument("--receipt", action="store_true")
    a = ap.parse_args()
    return {"prep": prep, "screen": screen}.get(a.step, lambda: score(a.receipt))()


if __name__ == "__main__":
    raise SystemExit(main())
