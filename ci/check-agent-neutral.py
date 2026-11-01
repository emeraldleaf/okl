#!/usr/bin/env python3
"""okl's docs are agent-neutral, and what only Claude Code has is labelled where it is said.

The check behind the `docs-agent-neutral` rule. The guide keeps a "Using another agent" section
that names `okl mcp`, and the README links to it. And in every tracked doc (README.md and all
of docs/), each paragraph, list item, or table row with its header, that names a Claude
Code-only surface (the Stop, prompt, pre-task and UserPromptSubmit hooks, the hook scripts,
`--format hook`, the /record, /triggers, /seed-from-codebase and /seed-from-docs commands) also
names Claude Code, a `.claude/` path or the `claude` command, or sits under a heading or a
lead-in that does. A mention that names no surface ("okl asks once what was learned") is beyond
a pattern; review reads those. The first version checked the section and the link only, so four
breaks that dropped "in Claude Code" from a sentence passed it (REPORT §4af, #318).
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ONLY = re.compile(r"(?<![\w/.-])/(record|triggers|seed-from-codebase|seed-from-docs)\b"
                  r"|\b(stop|prompt|pre-task|briefing|session-end)[- ]hooks?\b|\bUserPromptSubmit\b"
                  r"|\bsession-end question\b|\bokl's hooks\b|--format hook\b|(?<!pre-push )\bhook scripts?\b", re.I)
OTHERS = re.compile(r"\b([\w-]+)'s $")   # claude-mem's Stop hook is that tool's, not okl's
LABEL = re.compile(r"Claude Code|\.claude/|`claude( -p)?`", re.I)


def unlabelled(text: str) -> list[str]:
    """Each Claude Code-only mention in `text` that nothing around it labels."""
    found, headings = [], {}
    for block in re.split(r"\n\s*\n", text):
        lines = block.splitlines()
        for line in lines:
            if m := re.match(r"(#+)\s", line):
                headings = {k: v for k, v in headings.items() if k < len(m.group(1))}
                headings[len(m.group(1))] = line
        under = " ".join(headings.values())
        if block.lstrip().startswith("|"):
            units = [(row, lines[0]) for row in lines]
        else:   # each list item is its own statement; a label on the next one does not cover it,
            # but a lead-in that ends in a colon ("In Claude Code, two hooks run:") covers its list
            items = re.split(r"\n(?=\s*(?:[-*]|\d+\.)\s)", block)
            lead = items[0] if len(items) > 1 and items[0].rstrip().endswith(":") else ""
            units = [(item, lead) for item in items]
        for unit, header in units:
            for m in ONLY.finditer(unit):
                owner = OTHERS.search(unit[:m.start()])
                if owner and owner.group(1).lower() != "okl":
                    continue
                if not any(LABEL.search(t) for t in (unit, header, under)):
                    found.append(f"{m.group(0)!r} unlabelled in {' '.join(unit.split())[:90]!r}")
                break
    return found


if __name__ == "__main__":
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
        problems += [f"{doc}: {p}" for p in unlabelled((REPO / doc).read_text())]
    if problems:
        sys.exit("CLAUDE CODE LABELS MISSING: " + "; ".join(problems))
    print("AGENT NEUTRAL", len(docs), "docs")  # noqa: T201 - a check script reports on stdout
