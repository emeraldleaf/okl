#!/usr/bin/env python3
"""REPORT §4al's audit, as amended: two model annotators, and a person who adjudicates.

`build` takes the 120 audit pairs, labelled by the judge (Opus) and by an independent model (Sonnet's
own answers, before any decoy), and draws what the maintainer labels: every pair the two disagree on
(needed against not) and 10 seeded draws from the pairs they agree on, shuffled into one list. Each
pair carries excerpts of its change around the lines either model cited, so a pair opens on what was
argued over; the full change stays one click away. Neither model's answer is shown. It writes the
page's data and the private key to evals/bench/private/realwork/.

`score` reads the maintainer's labels and the key. A pair's final label is the maintainer's where
given and the two models' shared answer elsewhere. It passes when the maintainer overturns at most
one of the sampled agreements and kappa between the judge and the final labels, over the 120, is at
least 0.6. It writes evals/realwork/audit.json, which evals/realwork_reach.py reads.

    python3 evals/realwork_adjudicate.py build
    python3 evals/realwork_adjudicate.py score <labels.json>
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRIVATE = REPO / "evals" / "bench" / "private" / "realwork"
LABELS = REPO / "evals" / "realwork" / "labels.jsonl"
OUT = REPO / "evals" / "realwork" / "audit.json"
AGREEMENTS, SEED, CONTEXT, KAPPA_BAR, OVERTURN_MAX = 10, 45, 10, 0.6, 1


def needed(v: str | None) -> bool:
    """Whether an answer counts as needed."""
    return v == "needed"


def excerpts(diff: str, cited: list[str]) -> list[dict]:
    """The change's lines around each cited line, merged where they overlap, with their file."""
    lines = diff.splitlines()
    spans: list[tuple[int, int]] = []
    for c in cited:
        core = re.sub(r"^[+\- ]\s*", "", c.strip())[:60].strip()
        if len(core) < 8:
            continue
        hit = next((i for i, line in enumerate(lines) if core in line), None)
        if hit is None and len(core) > 30:
            hit = next((i for i, line in enumerate(lines) if core[:30] in line), None)
        if hit is not None:
            spans.append((max(0, hit - CONTEXT), min(len(lines), hit + CONTEXT + 1)))
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        file = next((line.split(" b/", 1)[-1] for line in reversed(lines[:a + 1]) if line.startswith("diff --git")), "")
        out.append({"file": file, "text": "\n".join(lines[a:b])})
    return out


def build() -> int:
    """Draw the pairs to adjudicate; write the page's data and the private key."""
    key = json.loads((PRIVATE / "audit-key.json").read_text())
    data = json.loads((PRIVATE / "audit-pairs.json").read_text())
    raw = json.loads((PRIVATE / "audit-suggester-raw.json").read_text())
    evidence = {}
    for line in LABELS.read_text().splitlines():
        r = json.loads(line)
        evidence[(r["pr"], r["lesson"])] = r.get("evidence") or ""
    pairs = {p["id"]: p for p in data["pairs"]}
    disagree = sorted(k for k, v in key.items() if needed(v["judge"]) != needed(v["suggested"]))
    agree = sorted(k for k, v in key.items() if needed(v["judge"]) == needed(v["suggested"]))
    rng = random.Random(SEED)  # noqa: S311 - a seeded draw, not a secret
    chosen = disagree + rng.sample(agree, AGREEMENTS)
    rng.shuffle(chosen)
    out_pairs, out_key = [], {}
    for n, pid in enumerate(chosen, 1):
        aid, p, k = f"a{n:02d}", pairs[pid], key[pid]
        diff = data["tasks"][str(p["pr"])]["diff"]
        cited = [evidence.get((p["pr"], k["lesson"]), ""), raw[pid].get("line", ""), raw[pid]["other"].get("line", "")]
        out_pairs.append({"id": aid, "pr": p["pr"], "lesson": p["lesson"], "excerpts": excerpts(diff, cited)})
        out_key[aid] = {"audit_id": pid, "kind": "disagree" if pid in disagree else "agree",
                        "judge": k["judge"], "other": k["suggested"]}
    tasks = {str(pr): data["tasks"][str(pr)] for pr in {p["pr"] for p in out_pairs}}
    (PRIVATE / "adjudication-pairs.json").write_text(json.dumps({"tasks": tasks, "pairs": out_pairs,
                                                                  "collection": "adjudication"}, ensure_ascii=False))
    (PRIVATE / "adjudication-key.json").write_text(json.dumps(out_key, indent=1))
    print(json.dumps({"pairs": len(out_pairs), "disagreements": len(disagree), "agreements_sampled": AGREEMENTS,
                      "with_excerpts": sum(1 for p in out_pairs if p["excerpts"]), "tasks": len(tasks)}))
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
    """Score the adjudication; write audit.json."""
    key = json.loads((PRIVATE / "audit-key.json").read_text())
    adj = json.loads((PRIVATE / "adjudication-key.json").read_text())
    raw = json.loads(Path(path).read_text())
    human = {k: (v.get("verdict") if isinstance(v, dict) else v) for k, v in raw.items()}
    given = {v["audit_id"]: human[a] for a, v in adj.items() if human.get(a) in ("needed", "related", "no", "unsure")}
    final = {pid: given.get(pid, v["judge"] if needed(v["judge"]) == needed(v["suggested"]) else None)
             for pid, v in key.items()}
    undecided = sorted(pid for pid, f in final.items() if f is None)
    sampled = [(a, v) for a, v in adj.items() if v["kind"] == "agree" and v["audit_id"] in given]
    overturned = sum(1 for a, v in sampled if needed(given[v["audit_id"]]) != needed(v["judge"]))
    scored = [pid for pid in key if final[pid] is not None]
    k = kappa([needed(key[p]["judge"]) for p in scored], [needed(final[p]) for p in scored])
    disagreements = [(a, v) for a, v in adj.items() if v["kind"] == "disagree" and v["audit_id"] in given]
    judge_right = sum(1 for a, v in disagreements if needed(given[v["audit_id"]]) == needed(v["judge"]))
    complete = len(given) == len(adj)
    passed = complete and overturned <= OVERTURN_MAX and k >= KAPPA_BAR
    out = {"section": "4al", "step": "audit (double annotation, adjudicated)",
           "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "adjudicated": len(given), "of": len(adj),
           "agreements_sampled": len(sampled), "agreements_overturned": overturned,
           "disagreements_adjudicated": len(disagreements), "judge_right_on_disagreements": judge_right,
           "kappa_judge_vs_final": round(k, 3), "pairs_scored": len(scored), "undecided": undecided,
           "bar": {"agreements_overturned_max": OVERTURN_MAX, "kappa": KAPPA_BAR}, "passed": passed,
           "status": "incomplete" if not complete else "passed" if passed else "failed"}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        raise SystemExit(build())
    if len(sys.argv) >= 3 and sys.argv[1] == "score":
        raise SystemExit(score(sys.argv[2]))
    sys.exit(__doc__)
