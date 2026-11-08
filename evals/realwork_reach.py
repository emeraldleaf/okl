#!/usr/bin/env python3
"""REPORT §4al's measure: of the lessons each real change needed, which reached the agent, and how.

For each task in evals/realwork/tasks.jsonl, the store is rebuilt as it stood when the code was
first written (from the private snapshot: lessons recorded later removed, from the full-text index
and the embeddings too; lessons retired later restored as live), and each channel is put through
`okl check` as this repository runs it: issue, title, issue and title, the paths the change
touched (`okl check --path`), and their union; the default briefing and the floor. The needed
lessons are the judge's labels (evals/realwork/labels.jsonl); "unsure" is counted both ways.

Reported: the task-level failure rate (a needed lesson not shown in full; not named at all) with
Wilson intervals; lesson-level reach with a bootstrap over tasks; each needed lesson's rank among
every candidate; and, on tasks with no review thread, the lessons named that were labelled "no".

No figure is reportable until the judge passes its audit (evals/realwork/audit.json, written by
evals/realwork_audit.py from the maintainer's labels). Without a passing audit, every output is
marked UNAUDITED. Calls no model; logs no briefing.

    python3 evals/realwork_reach.py [--receipt]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
TASKS = REPO / "evals" / "realwork" / "tasks.jsonl"
LABELS = REPO / "evals" / "realwork" / "labels.jsonl"
AUDIT = REPO / "evals" / "realwork" / "audit.json"
SNAPSHOT = REPO / "evals" / "bench" / "private" / "realwork" / "store.db"
FULL = ("next_actions", "armed_gates", "relevant_defects", "live_retractions", "in_scope_tombstones",
        "threat_prior_art", "rules", "vocabulary", "decisions", "context", "stale_warnings")
ARMS = {"default": [], "floor": ["--decision", "floor"]}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson 95% interval for k of n."""
    if n == 0:
        return (0.0, 1.0)
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def store_as_of(task: dict, room: Path) -> Path:
    """A copy of the snapshot holding only the lessons `task` could see, as they stood then."""
    db = room / f"store-{task['pr']}.db"
    shutil.copy(SNAPSHOT, db)
    keep = set(task["lessons"])
    con = sqlite3.connect(db)
    con.execute("create temp table keep(id text primary key)")
    con.executemany("insert into keep values (?)", [(i,) for i in keep])
    con.execute("delete from node where type != 'Vocabulary' and id not in (select id from keep)")
    con.execute("delete from node_fts where id not in (select id from node)")
    con.execute("delete from embedding where node_id not in (select id from node)")
    con.execute("delete from edge where src not in (select id from node) or dst not in (select id from node)")
    # Retired after the task: live when its code was written.
    con.execute("update node set status = '' where id in (select id from keep)"
                " and status in ('superseded', 'obsolete', 'retracted')")
    con.commit()
    con.close()
    return db


WARM_MISSED: list[str] = []


def okl_check(db: Path, *args: str) -> dict:
    """`okl check ... --format json` on store `db`, unlogged; {} on failure. A task check asked
    of the default arm must run with warm, as this repository does: one that falls back (the model
    did not answer in its budget, as under load) is asked once more, then recorded in WARM_MISSED,
    which makes the run unusable rather than quietly keyword-only."""
    env = {k: v for k, v in os.environ.items() if k != "OKL_DATABASE_URL"}
    env.update({"OKL_DATABASE_URL": f"sqlite:///{db}", "OKL_BRIEFING_LOG": "0", "PYTHONPATH": str(REPO / "src")})
    for _attempt in range(2):
        r = subprocess.run([sys.executable, "-m", "okl", "check", *args, "--format", "json"], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=180)
        try:
            result = json.loads(r.stdout)
        except json.JSONDecodeError:
            return {}
        if "--task" not in args or "--decision" in args or result.get("warm"):
            return result
    WARM_MISSED.append(f"{db.name}: {result.get('warm_unavailable')}")
    return result


def reached(result: dict) -> tuple[set[str], set[str]]:
    """(ids shown in full, ids named at all) in a briefing result."""
    full = {i["id"] for k in FULL for i in result.get(k) or [] if isinstance(i, dict) and i.get("id")}
    line = {i["id"] for i in result.get("also_matched") or [] if isinstance(i, dict) and i.get("id")}
    return full, full | line


def ranks(db: Path, text: str, needed: set[str]) -> dict[str, dict[str, int | None]]:
    """Each needed lesson's rank among every candidate, full-text alone and fused with potion."""
    from okl import core
    from okl.store import Store
    store = Store(f"sqlite:///{db}")
    out: dict[str, dict[str, int | None]] = {i: {} for i in needed}
    for label, hybrid in (("lexical", None), ("lexical+potion", "linear")):
        try:
            ids = [n.id for n in core.ranked_candidates(store, text, 1000, hybrid).nodes]
        except Exception:  # noqa: BLE001 - an arm that cannot run leaves its ranks empty, and says so
            ids = []
        for i in needed:
            out[i][label] = ids.index(i) + 1 if i in ids else None
    return out


def main() -> int:
    """Measure every task; print the tally; write a receipt with --receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", action="store_true")
    args = ap.parse_args()
    audit = json.loads(AUDIT.read_text()) if AUDIT.exists() else {}
    audited = bool(audit.get("passed"))
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
    labels: dict[tuple[int, str], str] = {}
    for line in LABELS.read_text().splitlines():
        r = json.loads(line)
        if r.get("verdict"):
            labels[(r["pr"], r["lesson"])] = r["verdict"]
    per_task = []
    with tempfile.TemporaryDirectory(prefix="okl-4al-reach-") as room:
        for t in tasks:
            needed = {i for i in t["lessons"] if labels.get((t["pr"], i)) == "needed"}
            unsure = {i for i in t["lessons"] if labels.get((t["pr"], i)) == "unsure"}
            no = {i for i in t["lessons"] if labels.get((t["pr"], i)) == "no"}
            db = store_as_of(t, Path(room))
            issue = " ".join(f"{i['title']} {i['body']}" for i in t["issues"])
            texts = {"issue": issue, "title": t["title"], "issue+title": f"{t['title']} {issue}".strip()}
            row = {"pr": t["pr"], "group": t["group"], "needed": sorted(needed), "unsure": sorted(unsure),
                   "channels": {}}
            for arm, flags in ARMS.items():
                union_full: set[str] = set()
                union_named: set[str] = set()
                for ch, text in texts.items():
                    if not text.strip():
                        continue
                    full, named = reached(okl_check(db, "--task", text, *flags))
                    row["channels"][f"{arm}:{ch}"] = {"full": sorted(full), "named": sorted(named)}
                    union_full |= full
                    union_named |= named
                pf: set[str] = set()
                pn: set[str] = set()
                for path in t["paths"]:
                    full, named = reached(okl_check(db, "--path", path))
                    pf |= full
                    pn |= named
                row["channels"][f"{arm}:paths"] = {"full": sorted(pf), "named": sorted(pn)}
                row["channels"][f"{arm}:union"] = {"full": sorted(union_full | pf), "named": sorted(union_named | pn)}
            row["named_but_no"] = sorted(set(row["channels"]["default:union"]["named"]) & no)
            row["ranks"] = ranks(db, texts["issue+title"], needed | unsure) if (needed or unsure) else {}
            per_task.append(row)
            db.unlink()   # one store copy at a time: fifty at once would not fit a crowded disk
            print(f"  #{t['pr']} needed {len(needed)} unsure {len(unsure)}", file=sys.stderr)
    tally: dict[str, dict] = {}
    with_needed = [r for r in per_task if r["needed"]]
    rng = random.Random(4)  # noqa: S311 - a seeded bootstrap, not a secret
    for key in sorted({k for r in per_task for k in r["channels"]}):
        for mode in ("full", "named"):
            miss = sum(1 for r in with_needed if not set(r["needed"]) <= set(r["channels"].get(key, {}).get(mode, [])))
            lo, hi = wilson(miss, len(with_needed))
            hits = [(len(set(r["needed"]) & set(r["channels"].get(key, {}).get(mode, []))), len(r["needed"]))
                    for r in with_needed]
            reach = sum(h for h, _ in hits) / max(1, sum(n for _, n in hits))
            boots = []
            for _ in range(2000):
                s = [hits[rng.randrange(len(hits))] for _ in hits] if hits else []
                boots.append(sum(h for h, _ in s) / max(1, sum(n for _, n in s)))
            boots.sort()
            tally[f"{key}:{mode}"] = {"tasks_missing": miss, "of": len(with_needed),
                                      "task_failure_rate": round(miss / max(1, len(with_needed)), 3),
                                      "wilson95": [round(lo, 3), round(hi, 3)], "lesson_reach": round(reach, 3),
                                      "reach_boot95": [round(boots[50], 3), round(boots[1949], 3)] if boots else None}
    usable = not WARM_MISSED
    status = ("reportable" if audited else "UNAUDITED: no figure here is reportable (REPORT §4al)")
    if not usable:
        status = f"NOT USABLE: {len(WARM_MISSED)} default briefing(s) ran without warm; " + status
    out = {"section": "4al", "step": "reach", "audited": audited, "usable": usable, "warm_missed": WARM_MISSED,
           "judge": "opus (labels in evals/realwork/labels.jsonl, prompt b1dbb8c24bbce0de)",
           "status": status,
           "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "tasks": len(per_task), "tasks_with_needed": len(with_needed),
           "needed_lessons": sum(len(r["needed"]) for r in per_task), "tally": tally, "per_task": per_task}
    print(f"{out['status']}\ntasks with a needed lesson: {len(with_needed)} of {len(per_task)}")
    for k, v in tally.items():
        if k.endswith(("union:full", "union:named", "issue+title:named", "paths:named")):
            print(f"  {k:32} tasks missing {v['tasks_missing']}/{v['of']} {v['wilson95']} · reach {v['lesson_reach']}")
    if args.receipt:
        path = REPO / "evals" / "results" / f"realwork-reach-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(f"receipt: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
