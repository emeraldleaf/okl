#!/usr/bin/env python3
"""For each prompt extract_prompts.py kept, the conversation the prompt hook could see before it (#294 follow-up, REPORT §4x).

    python3 evals/bench/extract_context.py [--projects ~/.claude/projects]

A real prompt is often terse because its subject is in the turns before it ("now do the
tests"). Claude Code hands the prompt hook a `transcript_path`, so the hook could read those
turns; this records, for the first occurrence of each prompt, what that transcript held at the
moment: the two typed prompts before it in the same session and the assistant's last text
reply, cut to its last MAX_REPLY characters. Typed prompts are found by extract_prompts.py's
own rule (user_text), so a harness wrapper is never taken for one. Writes
evals/bench/private/context.jsonl, which .gitignore keeps out of the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_prompts import user_text

OUT = Path(__file__).resolve().parent / "private" / "context.jsonl"
MAX_REPLY = 1500


def assistant_text(entry: dict) -> str | None:
    """The text blocks of a main-session assistant turn, or None when it has none."""
    if entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    content = entry.get("message", {}).get("content")
    if not isinstance(content, list):
        return None
    text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()
    return text or None


def main() -> None:
    """Walk every session transcript in order and write each kept prompt's context once."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--projects", default=str(Path.home() / ".claude" / "projects"))
    args = ap.parse_args()
    seen: set[str] = set()
    rows = []
    for path in sorted(Path(args.projects).glob("*/*.jsonl")):
        prev: list[str] = []
        reply = ""
        for line in path.open(errors="ignore"):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            said = assistant_text(entry)
            if said:
                reply = said[-MAX_REPLY:]
                continue
            text = user_text(entry)
            if text is None:
                continue
            pid = hashlib.sha256(re.sub(r"\s+", " ", text.lower()).strip().encode()).hexdigest()[:16]
            if pid not in seen:
                seen.add(pid)
                rows.append({"id": pid, "project": path.parent.name, "at": entry.get("timestamp"),
                             "previous": prev[-2:], "reply": reply})
            prev.append(text)
            reply = ""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with_context = sum(1 for r in rows if r["previous"] or r["reply"])
    print(f"{len(rows)} prompts, {with_context} with context before them -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
