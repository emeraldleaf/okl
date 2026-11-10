#!/usr/bin/env python3
"""REPORT §4al's audit of the judge: a sample for the maintainer to label blind, and its score.

`sample` draws 120 task-lesson pairs from the judge's labels, as registered: 40 it called needed,
40 it called no that share the most words with the task's text, and 40 it called no at random
(seeded). It writes the pairs for the labelling page, shuffled and with neither the judge's verdict
nor the stratum, to evals/bench/private/realwork/audit-pairs.json, and the key (verdict and
stratum per pair) to audit-key.json beside it. Both stay private until the audit is scored, so the
person labelling never sees what the judge said.

`score` reads the maintainer's labels (pair id to an answer, or the page's {verdict, suggested,
kept} documents), reports Cohen's kappa on needed against not, and the judge's misses among the
pairs the maintainer called needed, per stratum; with suggestions (as amended), also the decoys
kept, kappa where the suggester and the judge disagree, and kappa between them. It passes when every
pair is labelled, kappa >= 0.6, at most 2 misses in the random stratum and at most 5 decoys kept,
and writes evals/realwork/audit.json, which evals/realwork_reach.py reads.

    python3 evals/realwork_audit.py sample
    python3 evals/realwork_audit.py score <labels.json>
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "evals" / "realwork" / "tasks.jsonl"
LABELS = REPO / "evals" / "realwork" / "labels.jsonl"
PRIVATE = REPO / "evals" / "bench" / "private" / "realwork"
STORE = PRIVATE / "store.db"
OUT = REPO / "evals" / "realwork" / "audit.json"
PER_STRATUM, SEED, KAPPA_BAR, RANDOM_MISS_BAR, DECOYS_KEPT_MAX = 40, 4, 0.6, 2, 5
WORD = re.compile(r"[a-z][a-z0-9_]{3,}")


def words(text: str) -> set[str]:
    """The words of four letters or more in `text`, lower-cased."""
    return set(WORD.findall(text.lower()))


def task_text(t: dict) -> tuple[str, str]:
    """A task's text (title, issues, paths, the change's added lines) and the change itself."""
    diff = subprocess.run(["git", "-C", str(REPO), "diff", f"{t['base']}..{t['commit']}"],
                          capture_output=True, text=True, check=True).stdout
    added = "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    issues = " ".join(f"{i['title']} {i['body']}" for i in t["issues"])
    return f"{t['title']} {issues} {' '.join(t['paths'])} {added}", diff


def lesson_rows() -> dict[str, dict]:
    """Each lesson's text from the snapshot store."""
    con = sqlite3.connect(STORE)
    con.row_factory = sqlite3.Row
    out = {r["id"]: dict(r) for r in con.execute("select id, type, title, symptom, fix, body from node")}
    con.close()
    return out


def sample() -> int:
    """Draw the 120 pairs and write the page's data and the private key."""
    tasks = {t["pr"]: t for t in (json.loads(x) for x in TASKS.read_text().splitlines() if x.strip())}
    labels = [json.loads(x) for x in LABELS.read_text().splitlines() if x.strip()]
    lessons = lesson_rows()
    texts = {pr: task_text(t) for pr, t in tasks.items()}
    rng = random.Random(SEED)  # noqa: S311 - a seeded sample, not a secret
    needed = [r for r in labels if r.get("verdict") == "needed"]
    no = [r for r in labels if r.get("verdict") == "no"]

    def overlap(r: dict) -> int:
        lz = lessons[r["lesson"]]
        return len(words(texts[r["pr"]][0]) & words(" ".join(str(lz[k] or "") for k in ("title", "symptom", "fix", "body"))))
    chosen = [("needed", r) for r in rng.sample(needed, min(PER_STRATUM, len(needed)))]  # NOSONAR - seeded, reproducible on purpose
    by_overlap = sorted(no, key=overlap, reverse=True)
    high = by_overlap[:PER_STRATUM]
    rest = [r for r in no if r not in high]
    chosen += [("no-overlap", r) for r in high]
    chosen += [("no-random", r) for r in rng.sample(rest, min(PER_STRATUM, len(rest)))]  # NOSONAR - seeded, reproducible on purpose
    rng.shuffle(chosen)  # NOSONAR - seeded, reproducible on purpose
    pairs, key, diffs = [], {}, {}
    for n, (stratum, r) in enumerate(chosen, 1):
        pid = f"p{n:03d}"
        t, lz = tasks[r["pr"]], lessons[r["lesson"]]
        diffs[str(t["pr"])] = texts[t["pr"]][1][:60000]
        pairs.append({"id": pid, "pr": t["pr"], "lesson": {k: lz[k] for k in ("id", "type", "title", "symptom", "fix", "body")}})
        key[pid] = {"stratum": stratum, "judge": r["verdict"], "pr": r["pr"], "lesson": r["lesson"],
                    "overlap": overlap(r)}
    task_view = {str(pr): {"title": t["title"], "issues": t["issues"], "paths": t["paths"], "diff": diffs.get(str(pr), "")}
                 for pr, t in tasks.items() if str(pr) in diffs}
    PRIVATE.mkdir(parents=True, exist_ok=True)
    (PRIVATE / "audit-pairs.json").write_text(json.dumps({"tasks": task_view, "pairs": pairs}, ensure_ascii=False))
    (PRIVATE / "audit-key.json").write_text(json.dumps(key, indent=1))
    counts = {s: sum(1 for v in key.values() if v["stratum"] == s) for s in ("needed", "no-overlap", "no-random")}
    print(json.dumps({"pairs": len(pairs), "strata": counts, "tasks_shown": len(task_view),
                      "judge_needed_available": len(needed)}, indent=1))
    return 0


def kappa(a: list[bool], b: list[bool]) -> float:
    """Cohen's kappa between two lists of needed/not."""
    n = len(a)
    if not n:
        return 0.0
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def score(path: str) -> int:
    """Score the maintainer's labels against the judge's; write audit.json. `path` holds the page's
    labels: pair id -> an answer, or a document {verdict, suggested, kept}."""
    key = json.loads((PRIVATE / "audit-key.json").read_text())
    raw = json.loads(Path(path).read_text())
    human = {k: (v.get("verdict") if isinstance(v, dict) else v) for k, v in raw.items()}
    pairs = [(k, v) for k, v in key.items() if human.get(k) in ("needed", "related", "no", "unsure")]
    h = [human[k] == "needed" for k, _ in pairs]
    j = [v["judge"] == "needed" for _, v in pairs]
    misses = {s: sum(1 for (k, v) in pairs if v["stratum"] == s and human[k] == "needed" and v["judge"] != "needed")
              for s in ("needed", "no-overlap", "no-random")}
    out = {"section": "4al", "step": "audit", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
           "labelled": len(pairs), "of": len(key), "kappa": round(kappa(h, j), 3), "judge_misses": misses,
           "human_needed": sum(h), "unsure": sum(1 for k, _ in pairs if human[k] == "unsure"),
           "bar": {"kappa": KAPPA_BAR, "random_misses": RANDOM_MISS_BAR, "decoys_kept_max": DECOYS_KEPT_MAX}}
    suggested = any("decoy" in v for v in key.values())
    if suggested:
        decoys = [(k, v) for k, v in pairs if v.get("decoy")]
        kept = sum(1 for k, v in decoys if human[k] == v["shown"])
        split = [(k, v) for k, v in pairs if not v.get("decoy") and (v["suggested"] == "needed") != (v["judge"] == "needed")]
        shown_kept = sum(1 for k, v in pairs if not v.get("decoy") and human[k] == v["shown"])
        out["suggestions"] = {
            "decoys_kept": kept, "decoys_labelled": len(decoys), "void": kept > DECOYS_KEPT_MAX,
            "kept_rate_not_decoy": round(shown_kept / max(1, len(pairs) - len(decoys)), 3),
            "kappa_suggester_judge": round(kappa([v["suggested"] == "needed" for _, v in pairs],
                                                 [v["judge"] == "needed" for _, v in pairs]), 3),
            "kappa_where_suggester_and_judge_disagree": round(kappa(
                [human[k] == "needed" for k, _ in split], [v["judge"] == "needed" for _, v in split]), 3),
            "pairs_where_they_disagree": len(split)}
    complete = len(pairs) == len(key)
    void = bool(out.get("suggestions", {}).get("void"))
    out["passed"] = (complete and not void and out["kappa"] >= KAPPA_BAR and misses["no-random"] <= RANDOM_MISS_BAR)
    out["status"] = ("VOID: more decoys kept than the bar allows" if void
                     else "incomplete" if not complete else "passed" if out["passed"] else "failed")
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["passed"] else 1

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "sample":
        raise SystemExit(sample())
    if len(sys.argv) >= 3 and sys.argv[1] == "score":
        raise SystemExit(score(sys.argv[2]))
    sys.exit(__doc__)
