#!/usr/bin/env python3
"""REPORT §4am: three briefing arms on §4al's tasks, split by time.

The base is §4al's default union, read from its receipt, not re-run. Each arm is added to it:
- S, the standing set: the k lessons needed on the most development tasks, named wherever the
  task's store holds them (k = 10 decides, 20 is reported);
- R, the ranker's top: the first 17 lessons of the full-text search fused with the potion
  embedding on the issue and title;
- D, the diff re-brief: `okl check --task` on each changed file's path and added lines, cut to
  1,500 characters, as the default runs (warm on); the union over files.

The later 25 tasks decide (§4am's rule); the first 25 are reported beside them, in-sample.
Needs the warm model running (`okl warm start`), as §4al did.

    python3 evals/briefing_arms.py [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import realwork_reach as rr

REPO = rr.REPO
BASE_RECEIPT = REPO / "evals" / "results" / "realwork-reach-20261108-1548.json"
K, K_ALSO, TOP_N, CUT, SIZE_BAR, BOOT, SEED = 10, 20, 17, 1500, 10, 2000, 4


def sha256(path: Path) -> str:
    """The file's sha256, so the receipt names exactly what it read."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def halves(tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    """(development, test): the tasks in the order each was frozen, ties by PR number, cut in two."""
    order = sorted(tasks, key=lambda t: (t["at"], t["pr"]))
    mid = len(order) // 2
    return order[:mid], order[mid:]


def standing(dev: list[dict], needed: dict[int, set[str]], k: int) -> list[str]:
    """The k lessons needed on the most development tasks, ties broken by id."""
    counts = Counter(i for t in dev for i in needed[t["pr"]])
    return [i for i, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def ranker_top(db: Path, text: str, lessons: set[str]) -> list[str]:
    """The first TOP_N lessons of the full-text search fused with potion, on `text`."""
    from okl import core
    from okl.store import Store
    ids = [n.id for n in core.ranked_candidates(Store(f"sqlite:///{db}"), text, 1000, "linear").nodes]
    return [i for i in ids if i in lessons][:TOP_N]


def file_texts(task: dict) -> dict[str, str]:
    """Each changed file's path and added lines, whitespace collapsed, cut to CUT characters."""
    diff = subprocess.run(["git", "diff", "--no-color", task["base"], task["commit"]], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout
    added: dict[str, list[str]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[-1]
            added.setdefault(current, [])
        elif current and line.startswith("+") and not line.startswith("+++"):
            added[current].append(line[1:])
    out = {}
    for path in task["paths"]:
        body = re.sub(r"\s+", " ", " ".join(added.get(path, []))).strip()
        out[path] = f"{path} {body}".strip()[:CUT]
    return out


def tally(rows: list[dict], arm: str, labels: dict[tuple[int, str], str], rng: random.Random) -> dict:
    """Reach, its paired gain over the base, the failure rate and the cost, for one arm on one half."""
    with_needed = [r for r in rows if r["needed"]]
    hits = [(len(set(r["needed"]) & set(r["named"][arm])), len(set(r["needed"]) & set(r["named"]["base"])),
             len(r["needed"])) for r in with_needed]
    total = sum(n for _, _, n in hits)
    reach = sum(h for h, _, _ in hits) / max(1, total)
    base = sum(b for _, b, _ in hits) / max(1, total)
    gains = []
    for _ in range(BOOT):
        s = [hits[rng.randrange(len(hits))] for _ in hits]
        n = max(1, sum(x[2] for x in s))
        gains.append((sum(x[0] for x in s) - sum(x[1] for x in s)) / n)
    gains.sort()
    miss = sum(1 for r in with_needed if not set(r["needed"]) <= set(r["named"][arm]))
    lo, hi = rr.wilson(miss, len(with_needed))
    added = [sorted(set(r["named"][arm]) - set(r["named"]["base"])) for r in rows]
    return {"tasks": len(rows), "tasks_with_needed": len(with_needed), "needed": total,
            "reach": round(reach, 3), "base_reach": round(base, 3), "gain": round(reach - base, 3),
            "gain_boot95": [round(gains[int(0.025 * BOOT)], 3), round(gains[int(0.975 * BOOT) - 1], 3)],
            "tasks_missing": miss, "failure_rate": round(miss / max(1, len(with_needed)), 3),
            "failure_wilson95": [round(lo, 3), round(hi, 3)],
            "added_median": statistics.median(len(a) for a in added), "added_max": max(len(a) for a in added),
            "added_labelled_no": sum(1 for r, a in zip(rows, added, strict=True) for i in a
                                     if labels.get((r["pr"], i)) == "no")}


def main() -> int:
    """Run the arms on both halves; print the tally; write a receipt with --receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    tasks = [json.loads(line) for line in rr.TASKS.read_text().splitlines() if line.strip()]
    labels: dict[tuple[int, str], str] = {}
    for line in rr.LABELS.read_text().splitlines():
        r = json.loads(line)
        if r.get("verdict"):
            labels[(r["pr"], r["lesson"])] = r["verdict"]
    needed = {t["pr"]: {i for i in t["lessons"] if labels.get((t["pr"], i)) == "needed"} for t in tasks}
    base = {r["pr"]: r["channels"]["default:union"]["named"] for r in json.loads(BASE_RECEIPT.read_text())["per_task"]}
    dev, test = halves(tasks)
    s_k, s_also = standing(dev, needed, K), standing(dev, needed, K_ALSO)
    rows = []
    with tempfile.TemporaryDirectory(prefix="okl-4am-") as room:
        for t in dev + test:
            lessons = set(t["lessons"])
            db = rr.store_as_of(t, Path(room))
            issue = " ".join(f"{i['title']} {i['body']}" for i in t["issues"])
            r_top = ranker_top(db, f"{t['title']} {issue}".strip(), lessons)
            d_named: set[str] = set()
            for text in file_texts(t).values():
                d_named |= rr.reached(rr.okl_check(db, "--task", text))[1]
            db.unlink()   # one store copy at a time, as §4al ran
            b = set(base[t["pr"]])
            s10, s20 = {i for i in s_k if i in lessons}, {i for i in s_also if i in lessons}
            named = {"base": b, "S10": b | s10, "S20": b | s20, "R": b | set(r_top), "D": b | d_named,
                     "all": b | s10 | set(r_top) | d_named}
            rows.append({"pr": t["pr"], "half": "dev" if t in dev else "test", "needed": sorted(needed[t["pr"]]),
                         "named": {k: sorted(v) for k, v in named.items()}})
            print(f"  #{t['pr']} {rows[-1]['half']} needed {len(needed[t['pr']])} files {len(t['paths'])}",
                  file=sys.stderr)
    rng = random.Random(SEED)  # noqa: S311 - a seeded bootstrap, not a secret
    arms = ("S10", "S20", "R", "D", "all")
    result = {h: {a: tally([r for r in rows if r["half"] == h], a, labels, rng) for a in arms} for h in ("test", "dev")}
    t = result["test"]
    decisions = {a: {"adopt": t[a]["gain_boot95"][0] > 0 and t[a]["added_median"] <= SIZE_BAR,
                     "gain_lower_bound_above_zero": t[a]["gain_boot95"][0] > 0,
                     "added_median_within_bar": t[a]["added_median"] <= SIZE_BAR} for a in ("S10", "R", "D", "all")}
    predictions = {"S10 adds at least 8 points on the test half": t["S10"]["gain"] >= 0.08,
                   "D adds more than R": t["D"]["gain"] > t["R"]["gain"],
                   "all three still miss on more than half the test tasks": t["all"]["failure_rate"] > 0.5}
    usable = not rr.WARM_MISSED
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    out = {"section": "4am", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "okl_commit": head,
           "status": ("model-judged, not yet audited (#394)" if usable else
                      f"NOT USABLE: {len(rr.WARM_MISSED)} diff briefing(s) ran without warm"),
           "usable": usable, "warm_missed": rr.WARM_MISSED, "warm_fell_back_after_every_try": rr.WARM_FALLBACK,
           "warm_retries": len(rr.WARM_RETRIES),
           "inputs": {"labels_sha256": sha256(rr.LABELS), "tasks_sha256": sha256(rr.TASKS),
                      "store_sha256": sha256(rr.SNAPSHOT), "base_receipt": BASE_RECEIPT.name},
           "split": {"dev": [dev[0]["at"], dev[-1]["at"], len(dev)], "test": [test[0]["at"], test[-1]["at"], len(test)]},
           "parameters": {"k": K, "k_also": K_ALSO, "top_n": TOP_N, "cut": CUT, "size_bar": SIZE_BAR,
                          "bootstrap": BOOT, "seed": SEED},
           "standing_set": {"k10": s_k, "k20": s_also}, "result": result, "decisions": decisions,
           "predictions": predictions, "per_task": rows}
    print(out["status"])
    for h in ("test", "dev"):
        print(f"{h}{' (in-sample)' if h == 'dev' else ''}: base reach {result[h]['S10']['base_reach']}")
        for a in arms:
            v = result[h][a]
            print(f"  {a:4} reach {v['reach']} gain {v['gain']} {v['gain_boot95']} · missing on "
                  f"{v['tasks_missing']}/{v['tasks_with_needed']} · adds median {v['added_median']} max {v['added_max']}"
                  f" ({v['added_labelled_no']} labelled no)")
    print("decisions:", json.dumps(decisions))
    print("predictions:", json.dumps(predictions))
    if args.receipt:
        path = REPO / "evals" / "results" / f"briefing-arms-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(REPO)}")
    return 0 if usable else 2


if __name__ == "__main__":
    raise SystemExit(main())
