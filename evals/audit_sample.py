#!/usr/bin/env python3
"""The person's audit for #446: three sets of model answers, labelled blind on one private page.

No judge or answer key behind the series had been checked against a person (`docs/EVALUATION.md`
rule 7; the review on #446). This draws what the maintainer labels, with a fixed seed:

- **adjudication (21):** #394's pairs exactly as `realwork_adjudicate.py build` drew them (§4al's
  needed-or-not audit). Scored by that script, unchanged.
- **key (30):** pairs from the answer key behind §4ap/§4aq and the 124 breaks: 12 the key calls
  broken, 12 followed, 6 related, half from each half. Did the change need the lesson, and follow it?
- **judge (60):** patches from §4af, §4ah and §4bf, by the judge's verdict: 30 broken, 20 intact,
  10 with none. After the change, is the lesson's claim false? "Protection removed" is its own answer
  (#446 finding 8). A patch whose lesson text changed since its run is left out, so the person reads
  the words the judge read; §4af recorded no text hash, so its items are marked unchecked.

`build` writes the page's data (no model answer in it) and the private key, and a receipt of what was
drawn from where. `score` reads the page's labels and writes the audit's receipt.

    python3 evals/audit_sample.py build
    python3 evals/audit_sample.py score <labels.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr
import explain_search as es
import realwork_adjudicate as adj
import review_action as ra
import review_repo as rp
import run_guard

REPO = dr.REPO
RESULTS = dr.RESULTS
PRIVATE = REPO / "evals" / "bench" / "private" / "audit"
SEED = 446
KEY_DRAW = {"broken": 12, "followed": 12, "related": 6}
JUDGE_DRAW = {"broken": 30, "intact": 20, "none": 10}
JUDGE_RUNS = {"4af": "drift-mutate-20261031-1522", "4ah": "drift-mutate-20261101-1935", "4bf": "rule-mutate-20261114-1606"}
QUESTIONS = {
    "adjudication": {"ask": "Did this change need this lesson?",
                     "answers": {"needed": "Needed", "related": "Related, not needed", "no": "Not relevant", "unsure": "Unsure"}},
    "key": {"ask": "Did this change need this lesson, and did it follow it?",
            "answers": {"broken": "Needed, and the change broke it", "followed": "Needed, and the change followed it",
                        "related": "Related, not needed", "no": "Not relevant", "unsure": "Unsure"}},
    "judge": {"ask": "After this change, is the lesson's claim false of the repository?",
              "answers": {"broken": "Yes: the claim is now false", "protection": "Protection removed: what enforces it "
                          "is gone or weaker, but the claim still holds", "intact": "No: the claim still holds",
                          "unsure": "Unsure"}},
}


# Fields that would tell the person what a model answered, or which stratum an item came from.
ANSWER_FIELDS = frozenset({"judge", "key", "suggested", "verdict", "state", "kind", "run", "patch", "half", "other"})


def assert_blind(items: list[dict]) -> None:
    """Refuse page data that carries a model's answer or an item's stratum: the labels are blind."""
    leaked = sorted({f for i in items for f in i if f in ANSWER_FIELDS})
    if leaked:
        raise ValueError(f"the page's data would show {leaked}; the audit is blind")


def lesson_text(node: object) -> dict[str, str]:
    """What a labeller reads of a lesson: what the judge read."""
    return {"title": getattr(node, "title", "") or "", "symptom": getattr(node, "symptom", "") or "",
            "fix": getattr(node, "fix", "") or ""}


def evidence_of(half: str) -> dict[tuple[int, str], str]:
    """The line the needed-labeller cited for each pair, where it cited one."""
    rows = ({(r["pr"], r["lesson"]): r for r in map(json.loads, adj.LABELS.read_text().splitlines())}
            if half == "dev" else rp.keyed(rp.LABELS))
    return {k: (v.get("evidence") or "") for k, v in rows.items()}


def draw_key(rng: random.Random, nodes: dict) -> tuple[list[dict], dict, dict]:
    """KEY_DRAW pairs, half from each half, with their change and the lines the labeller cited."""
    items, key, population = [], {}, {}
    for half in ("dev", "test"):
        tasks = {t["pr"]: t for t in es.tasks_of(half)}
        k = es.key_of(half)
        ev = evidence_of(half)
        for cls, n in KEY_DRAW.items():
            pool = sorted(p for p, c in k.items() if c == cls and p[1] in nodes)
            population[f"{half}:{cls}"] = len(pool)
            for pr, lesson in rng.sample(pool, n // 2):
                task = tasks[pr]
                diff = ra.whole(task)
                items.append({"set": "key", "pr": pr, "title": task.get("title", ""), "lesson_id": lesson,
                              "lesson": lesson_text(nodes[lesson]), "excerpts": adj.excerpts(diff, [ev.get((pr, lesson), "")]),
                              "change": f"{half}:{pr}", "_diff": diff})
                key[len(items) - 1] = {"half": half, "key": cls}
    return items, key, population


def draw_judge(rng: random.Random, nodes: dict) -> tuple[list[dict], dict, dict]:
    """JUDGE_DRAW patches by the judge's verdict, from the three mutation runs."""
    pool: dict[str, list[tuple[str, dict]]] = {"broken": [], "intact": [], "none": []}
    left_out = Counter()
    for run, stem in JUDGE_RUNS.items():
        rec = json.loads((RESULTS / f"{stem}.json").read_text())
        shas = rec.get("lesson_sha") or {}
        for p in rec["patches"]:
            if not p.get("patch"):
                continue
            node = nodes.get(p["lesson"])
            if node is None:
                left_out["lesson gone"] += 1
                continue
            recorded = p.get("lesson_sha") or shas.get(p["lesson"])
            if recorded is not None and recorded != dr.text_sha(node):
                left_out["lesson text changed since the run"] += 1
                continue
            pool[p.get("judge") or "none"].append((run, {**p, "text_checked": recorded is not None}))
    items, key = [], {}
    population = {v: len(ps) for v, ps in pool.items()}
    for verdict, n in JUDGE_DRAW.items():
        for run, p in rng.sample(pool[verdict], min(n, len(pool[verdict]))):
            diff = (RESULTS / p["patch"]).read_text()
            items.append({"set": "judge", "lesson_id": p["lesson"], "lesson": lesson_text(nodes[p["lesson"]]),
                          "diff": diff, "files": sorted(set(dm_files(diff))), "text_checked": p["text_checked"]})
            key[len(items) - 1] = {"run": run, "patch": p["patch"], "kind": p["kind"], "judge": p.get("judge"),
                                   "docs_only": all(f.endswith(".md") or f.startswith("docs/") for f in dm_files(diff))}
    return items, key, {"population": population, "left_out": dict(left_out)}


def dm_files(diff: str) -> list[str]:
    """The files a unified diff changes, new ones included."""
    return [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]


def build(_args: argparse.Namespace) -> int:
    """Draw the three sets; write the page's data, the private key and the draw's receipt."""
    guard = run_guard.start()
    rng = random.Random(SEED)   # noqa: S311 - a seeded draw, reproducible on purpose
    with dr.store_copy(dr.main_store()) as store:
        nodes = {n.id: n for n in store.all_nodes()}
        store.close()
    a = json.loads((adj.PRIVATE / "adjudication-pairs.json").read_text())
    a_key = json.loads((adj.PRIVATE / "adjudication-key.json").read_text())
    adjudication = [{"set": "adjudication", "id": p["id"], "pr": p["pr"], "change": f"audit:{p['pr']}",
                     "_diff": a["tasks"][str(p["pr"])]["diff"],
                     "title": a["tasks"][str(p["pr"])].get("title", ""), "lesson_id": p["lesson"]["id"],
                     "lesson": {f: p["lesson"].get(f) or "" for f in ("title", "symptom", "fix")},   # as the models read it
                     "excerpts": p["excerpts"]} for p in a["pairs"]]
    k_items, k_key, k_pop = draw_key(rng, nodes)
    j_items, j_key, j_info = draw_judge(rng, nodes)
    order_k, order_j = list(range(len(k_items))), list(range(len(j_items)))
    rng.shuffle(order_k)
    rng.shuffle(order_j)
    key: dict[str, dict] = {p["id"]: {"set": "adjudication", **a_key[p["id"]]} for p in adjudication}
    items = list(adjudication)
    for n, i in enumerate(order_k, 1):
        items.append({**k_items[i], "id": f"k{n:02d}"})
        key[f"k{n:02d}"] = {"set": "key", **k_key[i], "pr": k_items[i]["pr"], "lesson": k_items[i]["lesson_id"]}
    for n, i in enumerate(order_j, 1):
        items.append({**j_items[i], "id": f"j{n:02d}"})
        key[f"j{n:02d}"] = {"set": "judge", **j_key[i], "lesson": j_items[i]["lesson_id"]}
    PRIVATE.mkdir(parents=True, exist_ok=True)
    # Each change's diff once: items that share a change point at it, and the page's data stays small.
    changes = {i["change"]: i.pop("_diff") for i in items if "_diff" in i}
    assert_blind(items)
    page = {"questions": QUESTIONS, "changes": changes, "items": items}
    body = json.dumps(page, ensure_ascii=False)
    (PRIVATE / "items.json").write_text(body)
    (PRIVATE / "key.json").write_text(json.dumps(key, indent=1))
    receipt = guard.stamp({
        "what": "the person's audit for #446: what was drawn, with no answer in it", "seed": SEED,
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "sets": dict(Counter(i["set"] for i in items)), "key_draw": KEY_DRAW, "key_population": k_pop,
        "judge_draw": JUDGE_DRAW, "judge_runs": JUDGE_RUNS, **{f"judge_{k}": v for k, v in j_info.items()},
        "items_sha256": hashlib.sha256(body.encode()).hexdigest(),
        # Not named "key": the secret scanner reads a hash under that word as an API key.
        "answers_file_sha256": hashlib.sha256((PRIVATE / "key.json").read_bytes()).hexdigest()})
    out = RESULTS / f"audit-draw-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: receipt[k] for k in ("sets", "key_population", "judge_population", "judge_left_out")}, indent=1))
    print(f"page data: {(PRIVATE / 'items.json').relative_to(REPO)} ({len(body) // 1024} KB); receipt: {out.relative_to(REPO)}")
    return 0


# The bars, committed before any label is read. Each says whether the model answers behind the series
# can be quoted as they stand; one missed means the figures that rest on them are corrected (errata).
KEY_BROKEN_PRECISION = 0.8     # of the pairs the key calls broken, the share the person also calls broken
JUDGE_BROKEN_PRECISION = 0.8   # of the patches the judge calls broken, the share the person calls broken
JUDGE_INTACT_PRECISION = 0.8   # of the patches the judge calls intact, the share the person calls intact


def answered(labels: dict, ids: list[str]) -> dict[str, str]:
    """The person's answer for each id that has one; "unsure" is an answer, kept apart."""
    out = {}
    for i in ids:
        v = labels.get(i)
        v = v.get("verdict") if isinstance(v, dict) else v
        if isinstance(v, str) and v:
            out[i] = v
    return out


def share(k: int, n: int) -> dict:
    """k of n with its Wilson 95% interval."""
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": dr.wilson(k, n)}


def score_key(key: dict, got: dict[str, str]) -> dict:
    """The key against the person: a confusion table, and the bar on what it calls broken."""
    ids = [i for i, v in key.items() if v["set"] == "key"]
    table = Counter(f'{key[i]["key"]}->{got[i]}' for i in ids if i in got)
    broken = [i for i in ids if key[i]["key"] == "broken" and i in got and got[i] != "unsure"]
    b = share(sum(got[i] == "broken" for i in broken), len(broken))
    return {"answered": sum(i in got for i in ids), "of": len(ids), "table": dict(table), "broken_precision": b,
            "bar": KEY_BROKEN_PRECISION, "passed": b["n"] > 0 and b["rate"] >= KEY_BROKEN_PRECISION}


def score_judge(key: dict, got: dict[str, str], population: dict[str, int]) -> dict:
    """The judge against the person, per verdict stratum, and sensitivity and specificity reweighted to
    the strata's sizes in the three runs (the draw took 30, 20 and 10 from strata of other sizes)."""
    ids = [i for i, v in key.items() if v["set"] == "judge"]
    table = Counter(f'{key[i]["judge"] or "none"}->{got[i]}' for i in ids if i in got)
    by = {s: [i for i in ids if (key[i]["judge"] or "none") == s and i in got and got[i] != "unsure"]
          for s in ("broken", "intact", "none")}
    pb = share(sum(got[i] == "broken" for i in by["broken"]), len(by["broken"]))
    pi = share(sum(got[i] in ("intact", "protection") for i in by["intact"]), len(by["intact"]))
    pn = share(sum(got[i] == "broken" for i in by["none"]), len(by["none"]))
    # Estimated counts in the runs of truly broken patches, by the judge's verdict.
    est = {s: population[s] * (r["rate"] or 0.0) for s, r in (("broken", pb), ("intact", {"rate": 1 - (pi["rate"] or 0.0)}),
                                                             ("none", pn))}
    true_broken = sum(est.values())
    sensitivity = round(est["broken"] / true_broken, 4) if true_broken else None
    false_broken = population["broken"] * (1 - (pb["rate"] or 0.0))
    true_intact = population["intact"] * (pi["rate"] or 0.0) + population["none"] * (1 - (pn["rate"] or 0.0)) + false_broken
    specificity = round(1 - false_broken / true_intact, 4) if true_intact else None
    return {"answered": sum(i in got for i in ids), "of": len(ids), "table": dict(table),
            "broken_precision": pb, "intact_precision": pi, "none_broken_share": pn,
            "protection_removed": sum(got.get(i) == "protection" for i in ids),
            "sensitivity_reweighted": sensitivity, "specificity_reweighted": specificity,
            "bars": {"broken_precision": JUDGE_BROKEN_PRECISION, "intact_precision": JUDGE_INTACT_PRECISION},
            "passed": (pb["n"] > 0 and pb["rate"] >= JUDGE_BROKEN_PRECISION and pi["n"] > 0
                       and pi["rate"] >= JUDGE_INTACT_PRECISION)}


def score(args: argparse.Namespace) -> int:
    """Score all three sets from the page's labels; #394's through its own script, unchanged."""
    guard = run_guard.start()
    key = json.loads((PRIVATE / "key.json").read_text())
    labels = json.loads(Path(args.labels).read_text())
    got = answered(labels, list(key))
    draw = json.loads(sorted(RESULTS.glob("audit-draw-*.json"))[-1].read_text())
    adj_labels = PRIVATE / "adjudication-labels.json"
    adj_labels.write_text(json.dumps({i: v for i, v in got.items() if key[i]["set"] == "adjudication"}))
    adj.score(str(adj_labels))
    out = guard.stamp({"what": "the person's audit for #446", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                       "draw_items_sha256": draw["items_sha256"],
                       "adjudication": json.loads(adj.OUT.read_text()),
                       "key": score_key(key, got), "judge": score_judge(key, got, draw["judge_population"])})
    dest = RESULTS / f"audit-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k].get("passed", out[k].get("status")) for k in ("adjudication", "key", "judge")}))
    print(f"receipt: {dest.relative_to(REPO)}")
    return 0


def main() -> int:
    """Run the named step."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(func=build)
    s = sub.add_parser("score")
    s.add_argument("labels")
    s.set_defaults(func=score)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
