#!/usr/bin/env python3
"""Held-fixed A/B: does the okl briefing reduce defect reproduction?

Two arms per task, same generator, ONLY the briefing differs:
  baseline : the task alone
  briefed  : `okl check --task <task>` briefing + the task

Outcome per (task, arm): did the generated code reproduce the task's known defect
class, judged BLIND (the judge sees task + code + defect signal, never the arm) by a
model that must differ from the generator (refused otherwise).

Eval-integrity rules enforced (they are stored lessons; this harness obeys them):
  - judge != generator, refused at startup
  - the report LEADS with its own failure count; RESULTS NOT USABLE above threshold
  - generator/judge run in a clean temp cwd so repo hooks can't inject themselves

Usage:
  python3 evals/ab_harness.py [--limit N] [--dry-run] [--timeout SECS]
Env:
  GENERATOR_CMD  (default: "claude -p --model sonnet")
  JUDGE_CMD      (default: "claude -p --model haiku")
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FAILURE_RATE_UNUSABLE = 0.20

GENERATOR_CMD = os.environ.get("GENERATOR_CMD", "claude -p --model sonnet")
JUDGE_CMD = os.environ.get("JUDGE_CMD", "claude -p --model haiku")

GEN_PROMPT = """You are implementing one task for an existing codebase. Output ONLY the code (or YAML/script), no explanation.

{briefing}TASK: {task}"""

BRIEFING_HEADER = "Read this briefing from your org's knowledge layer before implementing:\n\n{briefing}\n\n---\n\n"

JUDGE_PROMPT = """You are auditing a code submission for ONE specific defect class. Be strict and literal: judge only this defect, not general quality.

The developer was asked: {task}

Defect class to check for: {signal}

Submitted code:
```
{output}
```

Respond with ONLY this JSON, nothing else:
{{"defect_reproduced": true or false, "reason": "<one sentence citing the evidence>"}}"""


def call(cmd: str, prompt: str, timeout: int, workdir: str) -> str:
    r = subprocess.run(shlex.split(cmd), input=prompt, capture_output=True, text=True,
                       timeout=timeout, cwd=workdir)
    if r.returncode != 0:
        raise RuntimeError(f"exit {r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def get_briefing(task: str, timeout: int) -> str:
    # Fails CLOSED: a briefed arm without a briefing would silently become a second
    # baseline arm and corrupt the comparison.
    # --interests "" : unfiltered, matching evals/preflight.py. The host repo's interests
    # are not the experiment's — react_fetch's rule is tagged `react`, which okl does not
    # declare, so inheriting them made that task measure its rule's ABSENCE across every run
    # in this report. The harness states its retrieval config instead of borrowing one.
    r = subprocess.run([sys.executable, "-m", "okl", "check", "--task", task,
                        "--format", "agent", "--interests", ""],
                       capture_output=True, text=True, timeout=timeout, cwd=REPO)
    if r.returncode != 0:
        raise RuntimeError(f"okl check failed: {r.stderr.strip()[:200]}")
    return r.stdout


def parse_judge(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in judge output: {raw.strip()[:120]}")
    d = json.loads(m.group(0))
    if not isinstance(d.get("defect_reproduced"), bool):
        raise ValueError(f"judge JSON missing boolean defect_reproduced: {d}")
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(REPO / "evals" / "tasks.jsonl"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--samples", type=int, default=1,
                    help="repetitions per (task, arm) — single samples are noisy; ≥3 for citable numbers")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if GENERATOR_CMD.strip() == JUDGE_CMD.strip():
        print("REFUSING TO RUN: JUDGE_CMD == GENERATOR_CMD — the judge must not grade "
              "its own homework (qz_judge_self).", file=sys.stderr)
        return 3

    tasks = [json.loads(line) for line in Path(args.tasks).read_text().splitlines() if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    # Every task's defect_node must resolve to a real record. It is provenance, not an
    # input to judging, which is exactly why it rotted unnoticed: `r_pin_gating_tool` was
    # recorded in eight receipts while the record is `r_pin_gating_tools`, so those results
    # could not be traced back to the lesson they test.
    #
    # Client(), not Store(): a bare Store() defaults to sqlite:///okl.db in the CURRENT
    # directory and silently creates an empty one, so the check would have "found" every
    # reference missing while pointing at a database that never existed. Client walks up to
    # the configured .okl/ the way every other command does.
    if not args.dry_run:
        # Retrieval is deterministic, so whether each task still receives the rule it tests
        # is answerable in milliseconds. Checking it AFTER a 25-minute run is how §4d cost
        # what it cost. Refused here, before anything is spent.
        pf = subprocess.run([sys.executable, str(Path(__file__).parent / "preflight.py")],
                            capture_output=True, text=True)
        print(pf.stdout, end="")
        if pf.returncode != 0:
            print("REFUSING TO RUN: pre-flight failed (see above).")
            return 5

        from okl.client import Client
        _client = Client()
        _nodes = {n.id for n in _client.all_nodes()}
        missing = [(t["id"], t["defect_node"]) for t in tasks
                   if t.get("defect_node") and t["defect_node"] not in _nodes]
        if missing:
            print("REFUSING TO RUN: task(s) cite a defect_node that is not in the store —")
            for tid, node in missing:
                print(f"  {tid}: {node}")
            print("Fix the id in tasks.jsonl, or seed the record it names.")
            return 4

    n_runs = len(tasks) * 2 * args.samples
    if args.dry_run:
        for t in tasks:
            print(f"— {t['id']}  (defect: {t['defect_node']})")
        print(f"\n{len(tasks)} task(s) × 2 arms × {args.samples} sample(s) = "
              f"{n_runs} generations + {n_runs} judgments")
        print(f"generator: {GENERATOR_CMD}\njudge:     {JUDGE_CMD}")
        return 0

    results, failures = [], []
    with tempfile.TemporaryDirectory(prefix="okl-ab-") as clean_cwd:
        for t in tasks:
            # The briefing is deterministic per task — fetch once, reuse across samples.
            try:
                briefed_header = BRIEFING_HEADER.format(briefing=get_briefing(t["task"], args.timeout))
            except Exception as e:  # noqa: BLE001 — fail closed: no briefing, no briefed arm
                briefed_header = None
                brief_err = str(e)[:300]
            for s in range(args.samples):
                for arm in ("baseline", "briefed"):
                    rec = {"task": t["id"], "arm": arm, "sample": s, "defect_node": t["defect_node"]}
                    t0 = time.time()
                    try:
                        if arm == "briefed" and briefed_header is None:
                            raise RuntimeError(f"briefing unavailable (fail closed): {brief_err}")
                        briefing = briefed_header if arm == "briefed" else ""
                        code = call(GENERATOR_CMD, GEN_PROMPT.format(briefing=briefing, task=t["task"]),
                                    args.timeout, clean_cwd)
                        verdict = parse_judge(call(
                            JUDGE_CMD,
                            JUDGE_PROMPT.format(task=t["task"], signal=t["signal"], output=code[:8000]),
                            args.timeout, clean_cwd))
                        rec.update(reproduced=verdict["defect_reproduced"], reason=verdict["reason"],
                                   seconds=round(time.time() - t0, 1))
                        results.append(rec)
                        print(f"  {t['id']:16} {arm:8} s{s} → "
                              f"{'REPRODUCED' if rec['reproduced'] else 'clean':10} "
                              f"({rec['seconds']}s)", flush=True)
                    except Exception as e:  # noqa: BLE001 — every failure must be COUNTED, not raised past
                        rec.update(error=str(e)[:300], seconds=round(time.time() - t0, 1))
                        failures.append(rec)
                        print(f"  {t['id']:16} {arm:8} s{s} → FAILED: {str(e)[:80]}", flush=True)

    # ---- report: failure count FIRST (qz_judge_crash) ----
    total = len(results) + len(failures)
    frate = len(failures) / total if total else 1.0
    print(f"\n=== A/B REPORT ===\nruns: {total}   FAILURES: {len(failures)} ({frate:.0%})")
    if frate > FAILURE_RATE_UNUSABLE:
        print("❌ RESULTS NOT USABLE — failure rate above threshold. Fix the harness before "
              "reading any number below.")
    def by(arm):
        return [r for r in results if r["arm"] == arm]

    for arm in ("baseline", "briefed"):
        rows = by(arm)
        rep = sum(r["reproduced"] for r in rows)
        print(f"  {arm:8}: defect reproduced in {rep}/{len(rows)} runs"
              + (f"  ({rep/len(rows):.0%})" if rows else ""))
    if args.samples > 1:
        print("  per task (reproduced/samples):")
        for t in tasks:
            b = [r for r in by("baseline") if r["task"] == t["id"]]
            f = [r for r in by("briefed") if r["task"] == t["id"]]
            print(f"    {t['id']:16} baseline {sum(r['reproduced'] for r in b)}/{len(b)}"
                  f"   briefed {sum(r['reproduced'] for r in f)}/{len(f)}")
    # conditional subset: tasks where the BASELINE arm failed at least once
    base_failed = {r["task"] for r in by("baseline") if r["reproduced"]}
    cond = [r for r in by("briefed") if r["task"] in base_failed]
    if cond:
        rep = sum(r["reproduced"] for r in cond)
        print(f"  briefed runs on the {len(base_failed)} task(s) the baseline failed at least once: "
              f"{rep}/{len(cond)} reproduced")
    out = REPO / "evals" / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    path = out / f"ab-{stamp}.json"
    path.write_text(json.dumps({
        "generator": GENERATOR_CMD, "judge": JUDGE_CMD, "failure_rate": round(frate, 3),
        "usable": frate <= FAILURE_RATE_UNUSABLE, "results": results, "failures": failures,
    }, indent=1) + "\n")
    print(f"\nwrote {path.relative_to(REPO)}")
    return 0 if frate <= FAILURE_RATE_UNUSABLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
