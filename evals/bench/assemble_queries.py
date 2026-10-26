#!/usr/bin/env python3
"""Check the generated query batches against GENERATION.md and write evals/bench/queries.jsonl.

    python3 evals/bench/assemble_queries.py <dir holding queries-*.jsonl> --generator <model>

The protocol's structural rules are checked here, mechanically, and a batch that breaks one is
refused with the reason: three queries per advice lesson (one per register), 6 to 40 words,
lesson ids that exist in the seed packs, and no content word of the lesson's title in its
paraphrase (the same stopword list the writers were given). Its rules about content (never
naming the lesson or its advice, a bug report never naming the cause or the fix) were
instructions to the writer; no script checks them. Ids are stable (lesson key and
register), and the split is the parity of the SHA-256 of the lesson id, so a lesson's three
queries always share it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evals" / "bench" / "queries.jsonl"
REGISTERS = ("ticket", "paraphrase", "bug-report")
STOP = {"a", "an", "the", "of", "to", "in", "for", "and", "or", "on", "with", "is", "are", "be", "it",
        "its", "by", "at", "as", "from", "not", "no"}


def words(text: str) -> list[str]:
    """Content-word candidates: runs of letters and digits, two characters or longer, so the "t"
    of a split contraction is not read as a shared word."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]


def advice_lessons() -> dict[str, dict]:
    """Every advice record (Rule, Defect, Gate, Decision) in the seed packs, by bench id."""
    out = {}
    for f in sorted((ROOT / "seed").glob("*.json")):
        for n in json.loads(f.read_text())["nodes"]:
            if n.get("type") in ("Rule", "Defect", "Gate", "Decision"):
                out[f"seed:{f.stem}:{n['key']}"] = n
    return out


def split_of(lesson: str) -> str:
    """A lesson's split: the parity of the SHA-256 of its id."""
    return "selection" if int(hashlib.sha256(lesson.encode()).hexdigest(), 16) % 2 == 0 else "heldout"


def main() -> None:
    """Validate the batches and write the query file, or refuse with every problem found."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batches", type=Path)
    ap.add_argument("--generator", required=True)
    args = ap.parse_args()
    lessons = advice_lessons()
    rows, problems = [], []
    for path in sorted(args.batches.glob("queries-*.jsonl")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                q = json.loads(line)
            except ValueError:
                problems.append(f"{path.name}:{i}: not JSON")
                continue
            lesson, reg, text = q.get("lesson"), q.get("register"), (q.get("text") or "").strip()
            if lesson not in lessons:
                problems.append(f"{path.name}:{i}: unknown lesson {lesson!r}")
                continue
            if reg not in REGISTERS:
                problems.append(f"{path.name}:{i}: register {reg!r}")
                continue
            n = len(text.split())
            if not 6 <= n <= 40:
                problems.append(f"{path.name}:{i}: {n} words")
            if reg == "paraphrase":
                # Whole words only, with a trailing apostrophe-s folded away, so "What's" is not
                # read as sharing "s" with "platform's".
                title = {w for w in words(re.sub(r"'s\b", "", lessons[lesson]["title"])) if w not in STOP}
                shared = sorted(title & set(words(re.sub(r"'s\b", "", text))))
                if shared:
                    problems.append(f"{path.name}:{i}: paraphrase shares title words {shared}")
            rows.append({"lesson": lesson, "register": reg, "text": text})
    by_lesson: dict[str, list[str]] = {}
    for r in rows:
        by_lesson.setdefault(r["lesson"], []).append(r["register"])
    for lesson, regs in sorted(by_lesson.items()):
        if sorted(regs) != sorted(REGISTERS):
            problems.append(f"{lesson}: registers {sorted(regs)}")
    missing = sorted(set(lessons) - set(by_lesson))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(f"assemble: {len(problems)} problem(s); queries.jsonl not written")
    with OUT.open("w") as f:
        for r in sorted(rows, key=lambda r: (r["lesson"], REGISTERS.index(r["register"]))):
            key = r["lesson"].split(":", 2)[2]
            f.write(json.dumps({"id": f"{key}:{r['register']}", **r, "split": split_of(r["lesson"]),
                                "generator": args.generator}) + "\n")
    sel = sum(1 for r in rows if split_of(r["lesson"]) == "selection")
    print(f"{len(rows)} queries for {len(by_lesson)} lessons ({sel} selection, {len(rows) - sel} held-out) -> {OUT}"
          + (f"; lessons with no queries yet: {len(missing)}" if missing else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
