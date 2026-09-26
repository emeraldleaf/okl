"""Deterministic pre-flight for a briefing LAYOUT change: is the new render lossless?

Fetches every eval task's check result once, through the same client the harness uses,
and renders it twice -- with `core.py` as it was at a git ref, and with the working
copy -- then checks that every
content-bearing fragment of the old briefing (each record's title, symptom, cause and
fix) still appears in the new one. No model is called; it answers in milliseconds.

Why it exists (REPORT §4i): the harness's briefed arm reads the live store, which grows
between runs, so a live A/B cannot separate "the layout changed" from "the content
changed". This proves the content did not, before any model call is spent.

    python3 evals/layout_preflight.py --old-ref main
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from okl import core as new  # noqa: E402
from okl.client import Client  # noqa: E402

PREFIXES = ("symptom: ", "cause: ", "fix: ", "→ ")


def fragments(briefing: str) -> set[str]:
    out = set()
    for raw in briefing.splitlines():
        ln = raw.strip()
        for pre in PREFIXES:
            if ln.startswith(pre):
                out.add(ln[len(pre):][:120])
        m = re.match(r"- \*\*(?:[A-Z]+: )?(.+?)\*\*", ln)
        if m:
            out.add(m.group(1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-ref", default="main")
    ap.add_argument("--interests", default=os.environ.get(
        "BRIEF_INTERESTS",
        "python,method,security,agent-safety,retrieval-design,eval-integrity,data-quality"))
    args = ap.parse_args()
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{args.old_ref}:src/okl/core.py"],
                         capture_output=True, text=True, check=True).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("okl.core_old", f.name)
    old = importlib.util.module_from_spec(spec)
    sys.modules["okl.core_old"] = old
    spec.loader.exec_module(old)

    # One retrieval per task, through the same client the harness's `okl check` uses (it
    # may be a remote service, not this machine's store), rendered by both renderers. The
    # old renderer ignores the fields the new one added, so only the layout differs.
    client = Client()
    client.interests = [i for i in args.interests.split(",") if i]
    total_old = total_new = 0
    lost_any = False
    for line in (REPO / "evals" / "tasks.jsonl").read_text().splitlines():
        task = json.loads(line)
        result = client.check(task["task"], repo="okl")
        a = old.render_check_for_agent(result)
        b = new.render_check_for_agent(result)
        total_old += len(a)
        total_new += len(b)
        lost = sorted(x for x in fragments(a) if x not in b)
        lost_any |= bool(lost)
        print(f"{task.get('id', task['task'][:24]):22} old {len(a):6}  new {len(b):6}  lost {len(lost)}")
        for x in lost[:3]:
            print(f"    lost: {x}")
    pct = 100 - round(100 * total_new / total_old)
    print(f"TOTAL old {total_old} chars, new {total_new} chars: {pct}% smaller")
    print("LAYOUT PRE-FLIGHT: LOST CONTENT" if lost_any else "LAYOUT PRE-FLIGHT OK: lossless")
    return 1 if lost_any else 0


if __name__ == "__main__":
    raise SystemExit(main())
