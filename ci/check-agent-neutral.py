#!/usr/bin/env python3
"""okl's docs are agent-neutral, and what only Claude Code has is labelled where it is said.

The check behind the `docs-agent-neutral` rule. The guide keeps a "Using another agent" section
that names `okl mcp`, and the README links to it. And in every tracked doc (README.md and all
of docs/), each paragraph, list item, or table row with its header, that names a Claude Code-only surface
(the Stop, UserPromptSubmit and pre-task hooks, the hook scripts, `--format hook`, the /record, /triggers
and /seed-from-codebase commands) also names Claude Code, a `.claude/` path or the `claude`
command, or sits under a heading that does. The first version checked the section and the link
only, so four breaks that dropped "in Claude Code" from a sentence passed it (REPORT §4af, #318).
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ONLY = re.compile(r"(?<![\w/.-])/(record|triggers|seed-from-codebase)\b|\bStop hook\b|\bUserPromptSubmit\b"
                  r"|\bpre-task hook\b|--format hook\b|\bhook scripts?\b", re.I)
LABEL = re.compile(r"Claude Code|\.claude/|`claude( -p)?`", re.I)

problems = []
guide = (REPO / "docs/GETTING-STARTED.md").read_text()
if not re.search(r"^#{2,3} Using another agent", guide, re.M) or "okl mcp" not in guide:
    problems.append("the guide has no 'Using another agent' section naming `okl mcp`")
if "GETTING-STARTED.md#using-another-agent" not in (REPO / "README.md").read_text():
    problems.append("the README does not link the guide's 'Using another agent'")

# Committed reality, not the working tree's untracked files (CLAUDE.md: audits read the repo).
docs = [d for d in subprocess.run(["git", "-C", str(REPO), "ls-files", "README.md", "docs/"],
                                  capture_output=True, text=True, check=True).stdout.split() if d.endswith(".md")]
for doc in docs:
    headings: dict[int, str] = {}
    for block in re.split(r"\n\s*\n", (REPO / doc).read_text()):
        lines = block.splitlines()
        for line in lines:
            if m := re.match(r"(#+)\s", line):
                headings = {k: v for k, v in headings.items() if k < len(m.group(1))}
                headings[len(m.group(1))] = line
        under = " ".join(headings.values())
        if block.lstrip().startswith("|"):
            units = [(row, lines[0]) for row in lines]
        else:   # each list item is its own statement; a label on the next one does not cover it
            units = [(item, "") for item in re.split(r"\n(?=\s*(?:[-*]|\d+\.)\s)", block)]
        for unit, header in units:
            m = ONLY.search(unit)
            if m and not any(LABEL.search(t) for t in (unit, header, under)):
                problems.append(f"{doc}: {m.group(0)!r} unlabelled in {' '.join(unit.split())[:90]!r}")

if problems:
    sys.exit("CLAUDE CODE LABELS MISSING: " + "; ".join(problems))
print("AGENT NEUTRAL", len(docs), "docs")  # noqa: T201 - a check script reports on stdout
