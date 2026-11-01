#!/usr/bin/env python3
"""What the UNCHECKED mark costs a briefing (#222): each eval task and probe prompt briefed from a
copy of this checkout's store through the client the prompt hook uses, so with the config's
interests, decision, hybrid, rerank and warm settings and drift's marks, rendered with the proof
marks and with them taken out.

    PYTHONPATH=src python3 evals/briefing_marks_size.py
        # writes evals/results/briefing-marks-size-<stamp>.txt

Both renders come from one result, so the difference is the marks and their footer alone. The
store is read through SQLite's backup into a temporary file, never opened in place; the receipt
holds counts, never a briefing's text.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from okl import core, drift  # noqa: E402
from okl.client import Client  # noqa: E402
from okl.store import Store  # noqa: E402


def main_store() -> Path:
    """The main checkout's store: a worktree has none of its own."""
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return (ROOT / common).resolve().parent / ".okl" / "okl.db"


def without_marks(result: dict) -> dict:
    """`result` with every proof mark and its count taken out."""
    out = copy.deepcopy(result)
    out.pop("unchecked", None)
    for value in out.values():
        for rec in value if isinstance(value, list) else []:
            if isinstance(rec, dict):
                rec.pop("proof", None)
    return out


def eligible(result: dict) -> int:
    """The briefed lessons the mark could reach, counted once each by drift's own test: warnings,
    retired lessons and lessons drift already marks are not in the denominator (review of #316)."""
    ids = {rec["id"] for key in drift._BRIEFED for rec in result.get(key) or []
           if isinstance(rec, dict) and rec.get("id") and drift.proof_eligible(rec, rec.get("drift"))}
    return len(ids)


def main() -> int:
    """Brief each prompt, render it both ways, and write the receipt."""
    config = json.loads((main_store().parent / "config.json").read_text())
    prompts = [("task", json.loads(x)["task"]) for x in (ROOT / "evals" / "tasks.jsonl").read_text().splitlines()
               if x.strip()]
    prompts += [("probe", p) for p in json.loads((ROOT / "evals" / "probe_prompts.json").read_text())["prompts"]]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "okl.db"
        src, dst = sqlite3.connect(f"file:{main_store()}?mode=ro", uri=True), sqlite3.connect(db)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        store = Store(f"sqlite:///{db}")
        # The hook's own path, over this copy and never a service: a bare core.check ignored the
        # config's decision, hybrid, rerank and warm settings (review of #316).
        client = Client(config=config)
        client.service_url, client._store = None, store
        try:
            records = len(store.all_nodes())
            for kind, text in prompts:
                res = client.check(text)
                marked, bare = core.render_check_for_agent(res), core.render_check_for_agent(without_marks(res))
                rows.append({"kind": kind, "full": res.get("match_count") or 0,
                             "listed": len(res.get("also_matched") or []), "unchecked": res.get("unchecked", 0),
                             "eligible": eligible(res), "chars": len(bare), "added": len(marked) - len(bare)})
        finally:
            store.close()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    briefed = [r for r in rows if r["full"] or r["listed"]]
    total, added = sum(r["chars"] for r in briefed), sum(r["added"] for r in briefed)
    lessons = sum(r["full"] + r["listed"] for r in briefed)
    reach = sum(r["eligible"] for r in briefed)
    lines = [f"briefing marks size (#222) · {datetime.now(UTC):%Y-%m-%dT%H:%MZ} · code {commit} · "
             f"{len(rows)} prompts ({sum(r['kind'] == 'task' for r in rows)} eval tasks, "
             f"{sum(r['kind'] == 'probe' for r in rows)} probe prompts) · a copy of the store ({records} records), "
             f"repo {client.repo} as the hook briefs it (decision {client.decision}, hybrid {client.hybrid}, "
             f"rerank {client.rerank}, warm {client.warm})",
             f"  {'kind':6} {'full':>5} {'listed':>7} {'eligible':>9} {'unchecked':>10} {'chars':>7} {'added':>6}"]
    lines += [f"  {r['kind']:6} {r['full']:>5} {r['listed']:>7} {r['eligible']:>9} {r['unchecked']:>10} {r['chars']:>7} {r['added']:>6}"
              for r in rows]
    lines.append(f"  briefed prompts {len(briefed)}: {sum(r['unchecked'] for r in briefed)} of the {reach} lessons the "
                 f"mark could reach are marked unchecked ({lessons} briefed in all); the marks add {added} characters to {total} "
                 f"({100 * added / total if total else 0:.1f}%)")
    out = ROOT / "evals" / "results" / f"briefing-marks-size-{datetime.now(UTC):%Y%m%d-%H%M}.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines) + f"\nreceipt: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
