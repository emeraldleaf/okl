#!/usr/bin/env python3
"""REPORT §4an: lessons that name the files they apply to, drafted blind and scored on §4al's tasks.

`draft` asks Sonnet (never Opus, the judge) for each lesson's path triggers, twenty lessons a call
with no tools, given only the lesson's text and this repository's file list at the split's boundary
commit. It sees no task, no label and no briefing. Answers land in evals/realwork/path-triggers.jsonl
as each batch returns, with the model and the prompt's sha256, so a rerun asks only for what is
missing.

`score` adds arm P to §4al's default union: every lesson in a task's store with an entry matching a
file the change touches, read by the rule `files` uses today. The later 25 tasks decide (§4am's
rule); the first 25 are reported beside them. It also reports what P adds beyond §4am's three arms
together.

    python3 evals/path_triggers.py draft
    python3 evals/path_triggers.py score --arms evals/results/briefing-arms-<stamp>.json [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import briefing_arms as ba
import realwork_label as rl
import realwork_reach as rr

from okl.store import path_matches

REPO = rr.REPO
OUT = REPO / "evals" / "realwork" / "path-triggers.jsonl"
MODEL = "sonnet"
DRAFTER = ["claude", "-p", "--model", MODEL, "--restricted", "--strict-mcp-config", "--output-format", "json",
           "--tools", ""]
BATCH, ROUNDS, WORKERS, TIMEOUT, FIELD_CUT = 20, 3, 3, 600, 600
GAIN_PREDICTED = 0.05

PROMPT = """A software team keeps lessons: rules, past defects and decisions. A tool shows an agent a lesson when the agent opens a file the lesson applies to, so each lesson needs a list of the repository paths it applies to.

Below are the repository's files and some lessons. For each lesson, give the fewest entries that cover the files where following the lesson would change what someone writes. Give an empty list when the lesson could apply to any file or you cannot tell: an empty list is a normal answer, and a list that covers most of the repository is worse than none.

An entry is one of: a file's path (README.md); a folder, ending in / (docs/); or a pattern, where * matches any characters including / (*.md, tests/test_*.py, .github/workflows/*). Name only paths in the list below, or patterns that match some of them.

Repository files:
{files}

Lessons:
{lessons}

Answer with only a JSON array holding one object per lesson: [{{"id": "<the lesson's id>", "paths": ["<entry>"]}}]"""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]


def load_tasks() -> list[dict]:
    """§4al's frozen tasks."""
    return [json.loads(line) for line in rr.TASKS.read_text().splitlines() if line.strip()]


def boundary_files(tasks: list[dict]) -> tuple[str, list[str]]:
    """The last development task's commit and the repository's files there: a later file cannot be named."""
    commit = ba.halves(tasks)[0][-1]["commit"]
    listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", commit], cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    return commit, listing.splitlines()


def lesson_texts(ids: set[str]) -> dict[str, str]:
    """Each lesson's title, symptom, cause and fix, as the snapshot holds them, each field cut."""
    con = sqlite3.connect(rr.SNAPSHOT)
    out = {}
    for i, title, symptom, body, fix in con.execute("select id, title, symptom, body, fix from node"):
        if i in ids:
            parts = [("title", title), ("when", symptom), ("cause", body), ("do", fix)]
            out[i] = "\n".join(f"  {k}: {v[:FIELD_CUT]}" for k, v in parts if v)
    con.close()
    return out


def ask(prompt: str, room: Path) -> list | None:
    """The drafter's array for `prompt`, or None when it gave none."""
    try:
        p = subprocess.run(DRAFTER, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=room)
    except subprocess.TimeoutExpired:
        return None
    try:
        result = json.loads(p.stdout).get("result") or ""
    except ValueError:
        result = p.stdout
    return rl.last_array(result)


def clean(paths: object) -> list[str]:
    """The entries of one answer: strings only, stripped, as drafted otherwise."""
    return [p.strip() for p in paths if isinstance(p, str) and p.strip()] if isinstance(paths, list) else []


def draft() -> int:
    """Ask for every lesson not yet answered under this prompt; append answers as batches land."""
    tasks = load_tasks()
    commit, files = boundary_files(tasks)
    ids = {i for t in tasks for i in t["lessons"]}
    texts = lesson_texts(ids)
    done: dict[str, list[str]] = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            if r.get("prompt") == PROMPT_SHA:
                done[r["lesson"]] = r["paths"]
    file_list = "\n".join(files)

    def one(batch: list[str], room: Path) -> list[dict]:
        block = "\n\n".join(f"id: {i}\n{texts[i]}" for i in batch)
        got = ask(PROMPT.format(files=file_list, lessons=block), room) or []
        wanted = set(batch)
        return [{"lesson": x["id"], "paths": clean(x.get("paths")), "model": MODEL, "prompt": PROMPT_SHA}
                for x in got if x.get("id") in wanted]

    with tempfile.TemporaryDirectory(prefix="okl-4an-") as tmp, OUT.open("a") as sink:
        room = Path(tmp)   # the drafter runs outside the repository, with no tools
        for _ in range(ROUNDS):
            todo = sorted(i for i in texts if i not in done)
            if not todo:
                break
            batches = [todo[n:n + BATCH] for n in range(0, len(todo), BATCH)]
            print(f"{len(todo)} lessons in {len(batches)} batches · {MODEL} prompt {PROMPT_SHA} · boundary {commit[:9]}",
                  file=sys.stderr)
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                for rows in pool.map(lambda b: one(b, room), batches):
                    for r in rows:
                        if r["lesson"] not in done:
                            done[r["lesson"]] = r["paths"]
                            sink.write(json.dumps(r, ensure_ascii=False) + "\n")
                    sink.flush()
    missing = sorted(i for i in texts if i not in done)
    counts = [len(v) for v in done.values()]
    print(json.dumps({"lessons": len(texts), "answered": len(done), "missing": missing, "with_entries": sum(1 for c in counts if c),
                      "empty": sum(1 for c in counts if not c), "entries_median": statistics.median(counts) if counts else 0,
                      "boundary": commit, "files_listed": len(files), "prompt": PROMPT_SHA, "model": MODEL}, indent=1))
    return 0 if not missing else 2


def score(args: argparse.Namespace) -> int:
    """Score arm P on both halves; print the tally; write a receipt with --receipt."""
    tasks = load_tasks()
    labels: dict[tuple[int, str], str] = {}
    for line in rr.LABELS.read_text().splitlines():
        r = json.loads(line)
        if r.get("verdict"):
            labels[(r["pr"], r["lesson"])] = r["verdict"]
    triggers: dict[str, list[str]] = {}
    for line in OUT.read_text().splitlines():
        r = json.loads(line)
        if r.get("prompt") == PROMPT_SHA:
            triggers[r["lesson"]] = r["paths"]
    missing = sorted({i for t in tasks for i in t["lessons"]} - set(triggers))
    base = {r["pr"]: set(r["channels"]["default:union"]["named"]) for r in json.loads(ba.BASE_RECEIPT.read_text())["per_task"]}
    arms_path = Path(args.arms)
    three = {r["pr"]: set(r["named"]["all"]) for r in json.loads(arms_path.read_text())["per_task"]}
    dev, test = ba.halves(tasks)
    half = {t["pr"]: "dev" for t in dev} | {t["pr"]: "test" for t in test}
    over_base, over_three = [], []
    for t in dev + test:
        needed = sorted(i for i in t["lessons"] if labels.get((t["pr"], i)) == "needed")
        p = {i for i in t["lessons"] if any(path_matches(g, f) for g in triggers.get(i, []) for f in t["paths"])}
        over_base.append({"pr": t["pr"], "half": half[t["pr"]], "needed": needed,
                          "named": {"base": sorted(base[t["pr"]]), "P": sorted(base[t["pr"]] | p)}})
        over_three.append({"pr": t["pr"], "half": half[t["pr"]], "needed": needed,
                           "named": {"base": sorted(three[t["pr"]]), "P": sorted(three[t["pr"]] | p)}})
    rng = random.Random(ba.SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    result: dict[str, dict] = {}
    for h in ("test", "dev"):
        rows = [r for r in over_base if r["half"] == h]
        added = [set(r["named"]["P"]) - set(r["named"]["base"]) for r in rows]
        needed_added = sum(len(a & set(r["needed"])) for r, a in zip(rows, added, strict=True))
        pack = [(i, i in r["named"]["base"], i in r["named"]["P"]) for r in rows for i in r["needed"] if i.startswith("seed:")]
        result[h] = {"P": ba.tally(rows, "P", labels, rng),
                     "P_beyond_the_three": ba.tally([r for r in over_three if r["half"] == h], "P", labels, rng),
                     "added_total": sum(len(a) for a in added), "added_needed": needed_added,
                     "needed_from_packs": {"pairs": len(pack), "base_named": sum(b for _, b, _ in pack),
                                           "P_named": sum(c for _, _, c in pack)}}
    t = result["test"]
    v = t["P"]
    decision = {"adopt": v["gain_boot95"][0] > 0 and v["added_median"] <= ba.SIZE_BAR,
                "gain_lower_bound_above_zero": v["gain_boot95"][0] > 0, "added_median_within_bar": v["added_median"] <= ba.SIZE_BAR}
    predictions = {"P adds at least 5 points on the test half": v["gain"] >= GAIN_PREDICTED,
                   "most lessons P adds are labelled no": v["added_labelled_no"] > t["added_total"] / 2,
                   "P adds reach beyond the three arms together": t["P_beyond_the_three"]["gain"] > 0}
    usable = not missing
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    counts = [len(triggers[i]) for i in triggers]
    out = {"section": "4an", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": head,
           "status": "model-judged, not yet audited (#394)" if usable else f"INCOMPLETE: {len(missing)} lesson(s) have no draft",
           "usable": usable, "missing": missing, "drafter": {"model": MODEL, "prompt": PROMPT_SHA},
           "drafted": {"lessons": len(triggers), "with_entries": sum(1 for c in counts if c), "empty": sum(1 for c in counts if not c)},
           "inputs": {"labels_sha256": ba.sha256(rr.LABELS), "tasks_sha256": ba.sha256(rr.TASKS), "store_sha256": ba.sha256(rr.SNAPSHOT),
                      "triggers_sha256": ba.sha256(OUT), "base_receipt": ba.BASE_RECEIPT.name, "arms_receipt": arms_path.name},
           "size_bar": ba.SIZE_BAR, "bootstrap": ba.BOOT, "seed": ba.SEED, "result": result, "decision": decision,
           "predictions": predictions, "per_task": over_base}
    print(out["status"])
    print(json.dumps({"drafted": out["drafted"], "result": result, "decision": decision, "predictions": predictions}, indent=1))
    if args.receipt:
        path = REPO / "evals" / "results" / f"path-triggers-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(REPO)}")
    return 0 if usable else 2


def main() -> int:
    """Dispatch `draft` or `score`."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("draft")
    s = sub.add_parser("score")
    s.add_argument("--arms", required=True, help="§4am's receipt")
    s.add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    return draft() if args.cmd == "draft" else score(args)


if __name__ == "__main__":
    raise SystemExit(main())
