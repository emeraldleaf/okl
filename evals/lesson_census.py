#!/usr/bin/env python3
"""What watches each lesson this repo recorded (REPORT §4ag): drift, CI, or nothing.

    PYTHONPATH=src python3 evals/lesson_census.py [--rev origin/main] [--run-checks]
        # writes evals/results/lesson-census-<stamp>.json
    PYTHONPATH=src python3 evals/lesson_census.py --judge evals/results/lesson-census-<stamp>.json
        # writes evals/results/stale-lessons-<stamp>.json

A recorded lesson is one of the store's own, not a seed pack's, that is not retired. Each is in
one class:
- watched: governed files and a stored check, so drift re-runs it when those files change;
- unverified: governed files but no stored check, which drift reports red until one passes;
- checked: a stored check but no governed files, left to CI by the repo's rule (#39);
- unchecked: neither, so nothing re-runs anything for it.

--run-checks runs each checked lesson's stored check once at --rev, as `okl verify` judges it
(exit 0 with the expected text), with §4ae's replayer: a scratch worktree, no OKL_ or
git-location variable. The store is read from a copy. The receipt holds ids, classes, types,
scopes and verdicts, never a lesson's text.

--judge runs §4ag on a census receipt: every unchecked lesson, ten checked lessons as they are
(negative controls) and ten with one planted false fact (positive controls,
lesson_census_planted.json), judged once each, blind and in a seeded order, by a model reading
the repository at the receipt's commit. Judgments are kept as they arrive, so a run that stops
resumes where it stopped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr

from okl.store import RETIRED_STATUSES, Node

SEED = 189
CONTROLS = 10
TIMEOUT = 300
PLANTED = Path(__file__).resolve().parent / "lesson_census_planted.json"
# Read-only tools; --restricted ignores every settings file, so no okl hook briefs the judge.
# --allowedTools takes the rest of the line, so it comes last and the prompt goes on stdin.
JUDGE = ["claude", "-p", "--model", "opus", "--restricted", "--strict-mcp-config", "--output-format", "json",
         "--tools", "Read,Grep,Glob", "--allowedTools", "Read", "Grep", "Glob"]
JUDGE_PROMPT = """You are checking whether a lesson a software project recorded about itself still holds.
The project's repository is your working directory, at the commit the project is at now. Read
whatever you need with your tools. Do not change anything.

The lesson:
Title: {title}
Symptom: {symptom}
Fix: {fix}
Body: {body}

Choose one verdict:
- "current": what the lesson says about this repository still holds.
- "stale": something it says about this repository no longer holds (a file, command, flag,
  function, behaviour or decision has changed or does not exist), so following it would mislead.
- "no claim": it says nothing this repository can confirm or contradict (advice in general, or a
  fact about another project).
- "unsure": you cannot decide.

Answer with one JSON object and nothing else:
{{"verdict": "current|stale|no claim|unsure", "evidence": ["path:line", ...], "reason": "one sentence", "checkable": true or false}}
"checkable" says whether a shell command could check what the lesson claims about this repository."""
VERDICTS = ("current", "stale", "no claim", "unsure")


def classify(n: Node) -> str:
    """The lesson's class by what could re-run its check (module docstring)."""
    checked = dr.parse_check(n.verified_by) is not None
    if n.files:
        return "watched" if checked else "unverified"
    return "checked" if checked else "unchecked"


def drawn(ids: list[str], salt: str = "") -> list[str]:
    """`ids` in seed-189 hash order: redrawn the same by anyone from the receipt."""
    return sorted(ids, key=lambda i: hashlib.sha256(f"{SEED}:{salt}{i}".encode()).hexdigest())


def plant(text: str, old: str, new: str) -> str:
    """`text` with every whole occurrence of `old` replaced by `new`."""
    return re.sub(rf"(?<![\w-]){re.escape(old)}(?![\w-])", new, text)


def parse_verdict(result: str) -> dict | None:
    """The judge's last valid JSON object, or None when its answer holds none."""
    return dr.last_object(result, lambda o: o.get("verdict") in VERDICTS)


def summarize(items: list[dict]) -> dict:
    """§4ag's measures from the judged items."""
    pop = [x for x in items if x["role"] == "population"]
    v = Counter(x.get("verdict") or "invalid" for x in pop)
    stale, decided = v["stale"], v["stale"] + v["current"]
    role = {r: Counter(x.get("verdict") or "invalid" for x in items if x["role"] == r) for r in ("negative", "positive")}
    stale_items = [x for x in pop if x.get("verdict") == "stale"]
    return {
        "population": len(pop), "verdicts": dict(v),
        "stale_rate": {"stale": stale, "decided": decided, "rate": round(stale / decided, 4) if decided else None,
                       "wilson95": dr.wilson(stale, decided)},
        "claim_share": {"claims": v["current"] + v["stale"] + v["unsure"], "of": len(pop)},
        "negatives_called_stale": role["negative"]["stale"], "negatives": dict(role["negative"]),
        "positives_called_stale": role["positive"]["stale"], "positives": dict(role["positive"]),
        "stale_checkable": sum(1 for x in stale_items if x.get("checkable") is True),
        "stale_by_type": dict(Counter(x["type"] for x in stale_items)),
        "stale_by_scope": dict(Counter(x["scope"] for x in stale_items)),
        "invalid_share": round(v["invalid"] / len(pop), 4) if pop else None,
    }


def judge(census_path: Path, workers: int) -> int:
    """Run §4ag on the census receipt and write its receipt."""
    census = json.loads(census_path.read_text())
    rev = dr.git("rev-parse", census["rev"]).strip()
    planted = {p["id"]: p for p in json.loads(PLANTED.read_text())["lessons"]}
    for p in planted.values():   # a planted name must be false at the commit the judge reads
        if subprocess.run(["git", "-C", str(dr.REPO), "grep", "-q", "-F", "-e", p["new"].rstrip("()"), rev]).returncode == 0:
            sys.exit(f"ABORT: planted name {p['new']!r} exists at {rev[:12]}")
    rows = {x["id"]: x for x in census["lessons"]}
    recorded = {i: x["sha"] for i, x in rows.items()} if all("sha" in x for x in rows.values()) else None
    dr.as_recorded({}, recorded)   # an old receipt is refused before any check runs
    with dr.store_copy(dr.main_store()) as store:
        nodes = {i: store.get_node(i) for i in rows}
    for i, p in planted.items():   # and each planted fact must be in its lesson to be changed
        if plant(getattr(nodes[i], p["field"]) or "", p["old"], p["new"]) == (getattr(nodes[i], p["field"]) or ""):
            sys.exit(f"ABORT: {p['old']!r} is not in {i}'s {p['field']}")
    checked = drawn([i for i, x in rows.items() if x["class"] == "checked"])
    # Negative controls: the first ten in the draw, not planted, whose check passes at rev.
    negatives: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        r = dr.Replayer(Path(tmp))
        try:
            for i in checked:
                if len(negatives) == CONTROLS:
                    break
                check = rows[i].get("check")   # as the census read it, not as the store holds it now
                if i not in planted and check and r.verdict(rev, *check) == "pass":
                    negatives.append(i)
        finally:
            r.close()
    items = ([{"id": i, "role": "population"} for i, x in rows.items() if x["class"] == "unchecked"]
             + [{"id": i, "role": "negative"} for i in negatives]
             + [{"id": i, "role": "positive", "planted": planted[i]} for i in planted])
    for x in items:
        x["type"], x["scope"] = rows[x["id"]]["type"], rows[x["id"]]["scope"]
    dr.as_recorded({x["id"]: nodes[x["id"]] for x in items}, recorded)
    order = {i: k for k, i in enumerate(drawn([x["id"] for x in items], salt="order:"))}
    items.sort(key=lambda x: order[x["id"]])

    partial = Path(tempfile.gettempdir()) / f"okl-stale-lessons-{census_path.stem}.jsonl"
    done = {}
    if partial.exists():
        for line in partial.read_text().splitlines():
            got = json.loads(line)
            done[got["id"]] = got
    room = Path(tempfile.mkdtemp(prefix="okl-judge-"))
    wt = room / "repo"
    dr.git("worktree", "add", "-q", "--detach", str(wt), rev)
    (wt / "okl-drift.json").unlink(missing_ok=True)   # the judge reads no check and no governed file list

    def one(x: dict) -> dict:
        if x["id"] in done:
            return {**x, **done[x["id"]]}
        n = nodes[x["id"]]
        text = {f: getattr(n, f) or "" for f in ("title", "symptom", "fix", "body")}
        if x["role"] == "positive":
            text = {f: plant(t, x["planted"]["old"], x["planted"]["new"]) for f, t in text.items()}
        out = {"id": x["id"]}
        try:
            p = subprocess.run(JUDGE, input=JUDGE_PROMPT.format(**text), capture_output=True, text=True,
                               timeout=TIMEOUT, cwd=wt)
            env = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
            got = parse_verdict(env.get("result") or "")
            out.update(got or {"error": (env.get("result") or p.stderr or "no output")[-300:]})
            out["cost_usd"], out["secs"] = env.get("total_cost_usd"), round((env.get("duration_ms") or 0) / 1000, 1)
        except subprocess.TimeoutExpired:
            out["error"] = "timed out"
        with partial.open("a") as f:
            f.write(json.dumps(out) + "\n")
        print(f"{x['role']:10} {x['id'][:24]:24} {out.get('verdict') or out.get('error', '')[:60]}", flush=True)
        return {**x, **out}

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            judged = list(pool.map(one, items))
    finally:
        dr.git("worktree", "remove", "--force", str(wt))
    receipt = {
        "what": "stale lessons (REPORT §4ag)", "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "code": dr.git("rev-parse", "--short=12", "HEAD").strip(), "rev": rev[:12], "census": census_path.name,
        "judge": " ".join(JUDGE), "seed": SEED, "negatives": negatives, "planted": PLANTED.name,
        "cost_usd": round(sum(x.get("cost_usd") or 0 for x in judged), 2),
        "summary": summarize(judged), "items": judged,
    }
    out = dr.RESULTS / f"stale-lessons-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt["summary"], indent=1))
    print(f"receipt: {out.relative_to(dr.REPO)}")
    return 0


def main() -> int:
    """Count the classes, optionally run the checked lessons' checks, and write the receipt; or judge."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="origin/main", help="the commit the checks run at")
    ap.add_argument("--run-checks", action="store_true", help="run each checked lesson's check at --rev")
    ap.add_argument("--judge", type=Path, help="run §4ag on this census receipt")
    ap.add_argument("--workers", type=int, default=3, help="judge sessions at once")
    args = ap.parse_args()
    if args.judge:
        return judge(args.judge.resolve(), args.workers)
    rev = dr.git("rev-parse", args.rev).strip()
    with dr.store_copy(dr.main_store()) as store:
        live = [n for n in store.all_nodes() if n.status not in RETIRED_STATUSES]
        store.close()
    nodes = [n for n in live if not n.id.startswith("seed:")]
    # Each lesson's text hash and check, so a judge run later reads them as this census did.
    rows = [{"id": n.id, "class": classify(n), "type": n.type, "scope": n.scope, "sha": dr.text_sha(n),
             "check": dr.parse_check(n.verified_by)} for n in nodes]
    if args.run_checks:
        with tempfile.TemporaryDirectory() as tmp:
            r = dr.Replayer(Path(tmp))
            try:
                for row, n in zip(rows, nodes, strict=True):
                    check = dr.parse_check(n.verified_by)
                    if row["class"] == "checked" and check:
                        row["verdict"] = r.verdict(rev, *check)
            finally:
                r.close()
    unchecked = [x for x in rows if x["class"] == "unchecked"]
    receipt = {
        "what": "lesson census (REPORT §4ag)",
        "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "code": dr.git("rev-parse", "--short=12", "HEAD").strip(),
        "rev": rev[:12],
        "store": {"recorded": len(rows), "seed": len(live) - len(rows)},
        "classes": dict(Counter(x["class"] for x in rows)),
        "unchecked_by_type": dict(Counter(x["type"] for x in unchecked)),
        "unchecked_by_scope": dict(Counter(x["scope"] for x in unchecked)),
        "checks_at_rev": dict(Counter(x["verdict"] for x in rows if "verdict" in x)) if args.run_checks else None,
        "lessons": rows,
    }
    out = dr.RESULTS / f"lesson-census-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "lessons"}, indent=1))
    print(f"receipt: {out.relative_to(dr.REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
