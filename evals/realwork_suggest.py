#!/usr/bin/env python3
"""Suggested answers for REPORT §4al's audit pairs, from a model that is not the judge, with decoys.

As amended before any audit label: Sonnet, with a prompt worded apart from the Opus judge's, reads
each task's change once and answers every audit pair on it, with a one-sentence reason, the line it
rests on, and the strongest case for the other answer. Twenty pairs, drawn by a seed, are decoys:
the page shows the other answer and its case instead. The suggestions shown go to
audit-suggestions.json (no decoy mark) and the decoys into audit-key.json; both stay in the private
folder. The maintainer is told decoys exist, not which.

    python3 evals/realwork_suggest.py
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PRIVATE = Path(__file__).resolve().parent / "bench" / "private" / "realwork"
SUGGESTER = ["claude", "-p", "--model", "sonnet", "--restricted", "--strict-mcp-config", "--output-format", "json",
             "--tools", ""]
DECOYS, SEED, TIMEOUT = 20, 44, 600
ANSWERS = ("needed", "related", "no", "unsure")
PROMPT = """A reviewer is deciding, for one code change, which of a team's recorded lessons applied to it.
Suggest an answer for each lesson below, for the reviewer to accept or change.

Answers:
- needed: the change does the thing the lesson is about, so the lesson applied (whether or not
  the change got it right); following it could change this code.
- related: same subject, but nothing in this change would be different.
- no: the change does not touch what the lesson is about. Shared words alone are not enough.
- unsure: it cannot be told from this change.

For each lesson give your answer, one sentence of reason, the line of the change it rests on (or
empty), and the strongest honest case for a different answer: "no" if you answered needed,
otherwise "needed", with its own reason and line.

TITLE: {title}

ISSUE:
{issues}

CHANGE (as first written, before review):
{change}

LESSONS:
{lessons}

Reply with one JSON array, one object per lesson, every pair id exactly once, and nothing else:
[{{"pair": "<pair id>", "answer": "needed|related|no|unsure", "reason": "...", "line": "...",
   "other": {{"answer": "needed|no", "reason": "...", "line": "..."}}}}]"""


def last_array(text: str) -> list | None:
    """The largest JSON array of objects carrying "pair" in `text`."""
    dec, found = json.JSONDecoder(), None
    for m in re.finditer(r"\[", text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if (isinstance(obj, list) and obj and all(isinstance(x, dict) and "pair" in x for x in obj)
                and (found is None or len(obj) >= len(found))):
            found = obj
    return found


def lesson_text(pid: str, lz: dict) -> str:
    """One lesson as the suggester sees it, under its pair id."""
    parts = [f"[{pid}] ({lz.get('type') or 'Lesson'}) {lz.get('title') or ''}"]
    parts += [f"  {k}: {str(lz[k])[:600]}" for k in ("symptom", "fix", "body") if lz.get(k)]
    return "\n".join(parts)


def suggest(task: dict, pairs: list[dict], room: Path) -> dict[str, dict]:
    """Suggestions for `pairs` on `task`, asking once more for any the first reply left out."""
    issues = "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in task["issues"]) or "(none)"
    out: dict[str, dict] = {}
    pending = list(pairs)
    for _ in range(2):
        if not pending:
            break
        prompt = PROMPT.format(title=task["title"], issues=issues, change=task["diff"],
                               lessons="\n\n".join(lesson_text(p["id"], p["lesson"]) for p in pending))
        try:
            r = subprocess.run(SUGGESTER, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=room)
            got = last_array(json.loads(r.stdout).get("result") or "") or []
        except (subprocess.TimeoutExpired, ValueError):
            got = []
        ids = {p["id"] for p in pending}
        for g in got:
            o = g.get("other") or {}
            if g.get("pair") in ids and g.get("answer") in ANSWERS and o.get("answer") in ("needed", "no"):
                out[g["pair"]] = {"answer": g["answer"], "reason": str(g.get("reason") or "")[:400],
                                  "line": str(g.get("line") or "")[:300],
                                  "other": {"answer": o["answer"], "reason": str(o.get("reason") or "")[:400],
                                            "line": str(o.get("line") or "")[:300]}}
        pending = [p for p in pending if p["id"] not in out]
    return out


def main() -> int:
    """Suggest for every pair, draw the decoys, write the shown suggestions and the key."""
    data = json.loads((PRIVATE / "audit-pairs.json").read_text())
    by_task: dict[int, list[dict]] = defaultdict(list)
    for p in data["pairs"]:
        by_task[p["pr"]].append(p)
    with tempfile.TemporaryDirectory(prefix="okl-4al-suggest-") as room:
        def one(pr: int) -> dict[str, dict]:
            got = suggest(data["tasks"][str(pr)], by_task[pr], Path(room))
            print(f"  #{pr}: {len(got)} of {len(by_task[pr])}", file=sys.stderr)
            return got
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(one, sorted(by_task)))
    best: dict[str, dict] = {k: v for r in results for k, v in r.items()}
    missing = [p["id"] for p in data["pairs"] if p["id"] not in best]
    if missing:
        print(f"no suggestion for {len(missing)} pair(s): {missing}; nothing written", file=sys.stderr)
        return 1
    rng = random.Random(SEED)  # noqa: S311 - a seeded draw, not a secret
    decoys = set(rng.sample(sorted(best), DECOYS))
    shown = {pid: ({"answer": s["other"]["answer"], "reason": s["other"]["reason"], "line": s["other"]["line"]}
                   if pid in decoys else {k: s[k] for k in ("answer", "reason", "line")})
             for pid, s in best.items()}
    key = json.loads((PRIVATE / "audit-key.json").read_text())
    for pid, s in best.items():
        key[pid].update({"suggested": s["answer"], "shown": shown[pid]["answer"], "decoy": pid in decoys})
    (PRIVATE / "audit-key.json").write_text(json.dumps(key, indent=1))
    (PRIVATE / "audit-suggestions.json").write_text(json.dumps(shown, ensure_ascii=False))
    (PRIVATE / "audit-suggester-raw.json").write_text(json.dumps(best, ensure_ascii=False))
    print(json.dumps({"pairs": len(best), "decoys": len(decoys), "suggester": SUGGESTER[3]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
