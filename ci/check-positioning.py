#!/usr/bin/env python3
"""okl's public docs keep its positioning: not novel, composes with memory tools, never claims to
beat them at recall.

The check behind the `n_d45d7bf64896` lesson. Two halves. The honest framing the lesson calls
load-bearing must still be there, in the words it was written in: WHERE-THIS-SITS's "not a novel
idea", "they're better at it" and "they compose", and the first post's "those tools are better at
it than anything I would build". And no sentence or table cell in README.md, CHANGELOG.md or
docs/ may claim the opposite: that okl beats, outperforms or replaces a memory tool, that its
recall or retrieval is better than theirs, or that it is the better memory store. The first
version grepped two files for a fixed list of phrases, so three rewordings in other docs passed
it (REPORT §4af, #318). Changing the positioning on purpose means superseding the lesson.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRAMING = {
    "docs/WHERE-THIS-SITS.md": ["This is not a novel idea", "they're better at it", "they compose"],
    "docs/posts/01-memory-that-outlives-the-run.md": ["those tools are better at it than anything I would build"],
}
RIVAL = (r"(mem0|zep|letta|cognee|claude-mem|agentmemory|those tools|these tools|memory (tools?|stores?|layers?"
         r"|infrastructure|backends?|systems?|products?))")
CLAIMS = [
    re.compile(rf"\b(beat|beats|beating|outperform\w*|surpass\w*|outdo\w*)\b[^.|]{{0,60}}\b({RIVAL[1:-1]}|recall|them)\b", re.I),
    re.compile(rf"\b{RIVAL}\b[^.|]{{0,40}}\b(beaten|outperformed|surpassed)\b", re.I),
    re.compile(r"\b(retrieval|recall)\b[^.|]{0,40}\bbetter than\b|\bbetter recall\b|\b(the|a) better memory\b"
               r"|\bbest\b.{0,12}\bmemory\b", re.I),
    re.compile(rf"(?<!not )(?<!never )(?<!n't )\breplac\w*\b(?: \w+){{0,3}} \b{RIVAL}\b", re.I),
    re.compile(r"\bnobody else (does|has|offers|verifies|checks)\b|\bnothing invalidates\b|\bno other tool\b|\bthe only tool\b|\bfirst tool to\b"
               r"|\bnot worth composing\b|\bworth composing with\b", re.I),
]

problems = []
for doc, phrases in FRAMING.items():
    text = " ".join((REPO / doc).read_text().split())
    problems += [f"{doc} no longer says {p!r}" for p in phrases if p not in text]

docs = [d for d in subprocess.run(["git", "-C", str(REPO), "ls-files", "README.md", "CHANGELOG.md", "docs/"],
                                  capture_output=True, text=True, check=True).stdout.split() if d.endswith(".md")]
for doc in docs:
    for unit in re.split(r"(?<=[.!?])\s+|\s\|\s", " ".join((REPO / doc).read_text().split())):
        for claim in CLAIMS:
            if m := claim.search(unit):
                problems.append(f"{doc}: {m.group(0)!r}")
                break

if problems:
    sys.exit("POSITIONING CHANGED: " + "; ".join(problems))
print("POSITIONING OK", len(docs), "docs")  # noqa: T201 - a check script reports on stdout
