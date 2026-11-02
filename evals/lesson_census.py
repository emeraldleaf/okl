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

--judge --section 4ai runs REPORT §4ai instead (#315): the same instrument, judge, seed,
negatives and planted facts, on a six-way scale that also names a wrong detail and an outlived
workaround, with two of the three outlived lessons §4ag's notes found as controls (OUTLIVED), taken
out of the population; the third, n_f215b68b925c, stays a planted control. The judge's worktree
withholds this experiment's own files (withhold). It writes evals/results/stale-review-<stamp>.json.
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
# REPORT §4ai: §4ag's prompt with a scale that names what §4ag's could not (#315).
JUDGE_PROMPT_4AI = """You are checking whether a lesson a software project recorded about itself still holds.
The project's repository is your working directory, at the commit the project is at now. Read
whatever you need with your tools. Do not change anything.

The lesson:
Title: {title}
Symptom: {symptom}
Fix: {fix}
Body: {body}

Choose one verdict:
- "current": the lesson's point holds of this repository, and so does every detail it states about it.
- "detail wrong": the point holds, but a detail it states about this repository (a path, name,
  command, flag, default or count) is wrong now.
- "outlived": the lesson advises a workaround, an interim step or a caution that a later change in
  this repository has made unnecessary.
- "stale": the lesson's point no longer holds of this repository.
- "no claim": it says nothing this repository can confirm or contradict (advice in general, or a
  fact about another project).
- "unsure": you cannot decide.

Answer with one JSON object and nothing else:
{{"verdict": "current|detail wrong|outlived|stale|no claim|unsure", "no_longer": "the lesson's words that no longer hold, or empty", "instead": "what the repository has instead, or empty", "evidence": ["path:line", ...], "reason": "one sentence", "checkable": true or false}}
"checkable" says whether a shell command could check what the lesson claims about this repository."""
VERDICTS_4AI = ("current", "detail wrong", "outlived", "stale", "no claim", "unsure")
QUESTIONED = ("detail wrong", "outlived", "stale")
# §4ai's outlived controls: lessons §4ag's notes found still advising a workaround whose fix has
# landed. n_f215b68b925c does too, but it is one of the planted controls, so it stays there alone.
OUTLIVED = ("harness-reads-a-moving-working-tree", "fastembed-cache-in-tmpdir")
SECTIONS = {"4ag": (JUDGE_PROMPT, VERDICTS), "4ai": (JUDGE_PROMPT_4AI, VERDICTS_4AI)}
# What §4ai's judge cannot see: this experiment's own files, which main holds since §4ag merged
# and which name the planted facts and §4ag's verdicts (REPORT §4ai, amended before judging).
WITHHELD_FILES = ("evals/lesson_census_planted.json", "evals/lesson_census.py", "tests/test_drift_replay.py")
WITHHELD_RECEIPTS = ("stale-lessons-*", "stale-review-*", "lesson-census-*")
WITHHELD_SECTIONS = ("4ag", "4ai")


def withhold(wt: Path) -> list[str]:
    """Remove this experiment's own files from the judge's worktree and blank its REPORT sections;
    return what was withheld."""
    gone = []
    for rel in WITHHELD_FILES:
        if (wt / rel).exists():
            (wt / rel).unlink(); gone.append(rel)
    for pattern in WITHHELD_RECEIPTS:
        for f in sorted((wt / "evals" / "results").glob(pattern)):
            f.unlink(); gone.append(str(f.relative_to(wt)))
    report = wt / "evals" / "REPORT.md"
    text = report.read_text()
    for section in WITHHELD_SECTIONS:
        m = re.search(rf"^## {section}\..*?(?=^## )", text, re.S | re.M)
        if m:
            text = text[:m.start()] + f"## {section}. (withheld from this judgment: it describes the run)\n\n" + text[m.end():]
            gone.append(f"evals/REPORT.md §{section}")
    report.write_text(text)
    return gone


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


def parse_verdict(result: str, verdicts: tuple[str, ...] = VERDICTS) -> dict | None:
    """The judge's last valid JSON object, or None when its answer holds none. On §4ai's scale, an
    answer that questions the lesson is valid only with the words that no longer hold and what the
    repository has instead, as §4ai registers (CLI review on the result's PR)."""
    def valid(o: dict) -> bool:
        if o.get("verdict") not in verdicts:
            return False
        if verdicts == VERDICTS_4AI and o["verdict"] in QUESTIONED:
            return all(isinstance(o.get(k), str) and o[k].strip() for k in ("no_longer", "instead"))
        return True
    return dr.last_object(result, valid)


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


def summarize_4ai(items: list[dict]) -> dict:
    """§4ai's measures from the judged items: the controls first, the rates only if they hold."""
    pop = [x for x in items if x["role"] == "population"]
    v = Counter(x.get("verdict") or "invalid" for x in pop)
    role = {r: Counter(x.get("verdict") or "invalid" for x in items if x["role"] == r)
            for r in ("negative", "positive", "outlived")}
    # A planted fact is caught as detail wrong or stale; on a planted lesson that also advises an
    # outlived workaround, an outlived verdict counts only when it quotes the planted name (§4ai).
    planted = sum(1 for x in items if x["role"] == "positive" and (
        x.get("verdict") in ("detail wrong", "stale")
        or (x.get("verdict") == "outlived" and x.get("planted", {}).get("new", "\0") in (x.get("no_longer") or ""))))
    over = sum(role["negative"][k] for k in ("detail wrong", "outlived", "stale"))
    outlived = sum(role["outlived"][k] for k in ("outlived", "detail wrong", "stale"))
    invalid = sum(1 for x in items if not x.get("verdict"))
    decided = sum(v[k] for k in ("current", "detail wrong", "outlived", "stale"))
    held = planted >= 8 and over <= 1 and invalid <= len(items) / 5
    # A missed outlived control means the review cannot find that kind (§4ai), so no outlived rate.
    kinds = QUESTIONED if outlived == len(OUTLIVED) else ("detail wrong", "stale")
    rates = {k: {"count": v[k], "decided": decided, "rate": round(v[k] / decided, 4) if decided else None,
                 "wilson95": dr.wilson(v[k], decided)} for k in kinds} if held else None
    questioned = [x for x in pop if x.get("verdict") in QUESTIONED]
    return {
        "population": len(pop), "verdicts": dict(v),
        "planted_caught": {"caught": planted, "of": sum(role["positive"].values())},
        "negatives_over_called": {"over": over, "of": sum(role["negative"].values())},
        "outlived_caught": {"caught": outlived, "of": sum(role["outlived"].values())},
        "controls": {r: dict(c) for r, c in role.items()},
        "predictions": {"1_planted_at_least_8": planted >= 8, "2_negatives_at_most_1": over <= 1,
                        "3_both_outlived": outlived == len(OUTLIVED)},
        "invalid_share": round(invalid / len(items), 4) if items else None,
        "rates": rates,
        "questioned_checkable": sum(1 for x in questioned if x.get("checkable") is True),
        "questioned_by_type": dict(Counter(x["type"] for x in questioned)),
    }


def judge(census_path: Path, workers: int, section: str = "4ag") -> int:
    """Run §4ag (or §4ai) on the census receipt and write its receipt."""
    prompt, verdicts = SECTIONS[section]
    outlived = OUTLIVED if section == "4ai" else ()
    census = json.loads(census_path.read_text())
    rev = dr.git("rev-parse", census["rev"]).strip()
    planted = {p["id"]: p for p in json.loads(PLANTED.read_text())["lessons"]}
    for p in planted.values() if section == "4ag" else ():   # §4ai checks the judge's own worktree, below
        if subprocess.run(["git", "-C", str(dr.REPO), "grep", "-q", "-F", "-e", p["new"].rstrip("()"), rev]).returncode == 0:
            sys.exit(f"ABORT: planted name {p['new']!r} exists at {rev[:12]}")
    rows = {x["id"]: x for x in census["lessons"]}
    if missing := [i for i in outlived if i not in rows]:
        sys.exit(f"ABORT: outlived controls not in the census: {missing}")
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
    items = ([{"id": i, "role": "population"} for i, x in rows.items()
              if x["class"] == "unchecked" and i not in outlived]
             + [{"id": i, "role": "negative"} for i in negatives]
             + [{"id": i, "role": "positive", "planted": planted[i]} for i in planted]
             + [{"id": i, "role": "outlived"} for i in outlived])
    for x in items:
        x["type"], x["scope"] = rows[x["id"]]["type"], rows[x["id"]]["scope"]
    dr.as_recorded({x["id"]: nodes[x["id"]] for x in items}, recorded)
    order = {i: k for k, i in enumerate(drawn([x["id"] for x in items], salt="order:"))}
    items.sort(key=lambda x: order[x["id"]])

    partial = Path(tempfile.gettempdir()) / f"okl-stale-{section}-{census_path.stem}.jsonl"
    done = {}
    if partial.exists():
        for line in partial.read_text().splitlines():
            got = json.loads(line)
            done[got["id"]] = got
    room = Path(tempfile.mkdtemp(prefix="okl-judge-"))
    wt = room / "repo"
    dr.git("worktree", "add", "-q", "--detach", str(wt), rev)
    (wt / "okl-drift.json").unlink(missing_ok=True)   # the judge reads no check and no governed file list
    withheld = withhold(wt) if section == "4ai" else []
    for p in planted.values() if section == "4ai" else ():   # false where the judge reads, or no run
        if subprocess.run(["grep", "-rqF", "--exclude-dir=.git", "-e", p["new"].rstrip("()"), str(wt)]).returncode == 0:
            dr.git("worktree", "remove", "--force", str(wt))
            sys.exit(f"ABORT: planted name {p['new']!r} is in the judge's worktree at {rev[:12]}")

    def one(x: dict) -> dict:
        if x["id"] in done:
            return {**x, **done[x["id"]]}
        n = nodes[x["id"]]
        text = {f: getattr(n, f) or "" for f in ("title", "symptom", "fix", "body")}
        if x["role"] == "positive":
            text = {f: plant(t, x["planted"]["old"], x["planted"]["new"]) for f, t in text.items()}
        out = {"id": x["id"]}
        try:
            p = subprocess.run(JUDGE, input=prompt.format(**text), capture_output=True, text=True,
                               timeout=TIMEOUT, cwd=wt)
            env = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
            got = parse_verdict(env.get("result") or "", verdicts)
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
    what = "stale lessons (REPORT §4ag)" if section == "4ag" else "a review of unchecked lessons (REPORT §4ai)"
    receipt = {
        "what": what, "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "code": dr.git("rev-parse", "--short=12", "HEAD").strip(), "rev": rev[:12], "census": census_path.name,
        "judge": " ".join(JUDGE), "seed": SEED, "negatives": negatives, "planted": PLANTED.name,
        "outlived": list(outlived), "withheld": withheld, "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        "cost_usd": round(sum(x.get("cost_usd") or 0 for x in judged), 2),
        "summary": summarize(judged) if section == "4ag" else summarize_4ai(judged), "items": judged,
    }
    stem = "stale-lessons" if section == "4ag" else "stale-review"
    out = dr.RESULTS / f"{stem}-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt["summary"], indent=1))
    print(f"receipt: {out.relative_to(dr.REPO)}")
    return 0


def main() -> int:
    """Count the classes, optionally run the checked lessons' checks, and write the receipt; or judge."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="origin/main", help="the commit the checks run at")
    ap.add_argument("--run-checks", action="store_true", help="run each checked lesson's check at --rev")
    ap.add_argument("--judge", type=Path, help="run §4ag (or --section 4ai) on this census receipt")
    ap.add_argument("--section", choices=sorted(SECTIONS), default="4ag", help="which registered run")
    ap.add_argument("--workers", type=int, default=3, help="judge sessions at once")
    args = ap.parse_args()
    if args.judge:
        return judge(args.judge.resolve(), args.workers, args.section)
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
