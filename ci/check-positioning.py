#!/usr/bin/env python3
"""okl's public docs keep its positioning: not novel, composes with memory tools, never claims to
beat them at recall.

The check behind the `n_d45d7bf64896` lesson. Two halves. The honest framing the lesson calls
load-bearing must still be there, in the words it was written in: WHERE-THIS-SITS's "not a novel
idea", "they're better at it" and "they compose", and the first post's "those tools are better at
it than anything I would build". And no sentence or table cell in README.md or docs/ may claim
the opposite: that okl beats, outranks, replaces or obsoletes a memory tool, that it is the
better or the first memory layer, or that the tools are not worth composing with. A comparison
counts only when a rival is named in it, so okl's own settings can be compared ("the tiered
decision beats the floor on recall"), and a negation just before the claim ("okl is not meant to
replace a memory store") clears it. It is a list of the shapes such claims have taken (in §4af's
breaks and two reviews), not a reader: a new shape passes until it is added. The first version grepped two files for a fixed list of phrases, so
three rewordings in other docs passed it (REPORT §4af, #318). CHANGELOG.md is history and may
quote a removed claim, so it is not read. Changing the positioning on purpose means superseding
the lesson.
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
RIVAL = (r"(?:mem0|zep|letta|cognee|claude-mem|agentmemory|those tools|these tools"
         r"|memory (?:tools?|stores?|layers?|infrastructure|backends?|systems?|products?))")
GOOD = r"(?:better|stronger|faster|smarter|richer|more (?:accurate|precise|reliable|complete|capable|useful))"
OVER = (rf"(?:beat\w*|outperform\w*|outrank\w*|outclass\w*|surpass\w*|outdo\w*|superior to"
        rf"|{GOOD}(?: [\w-]+){{0,3}}? than|more often than|more of [\w ]{{0,30}}? than)")
CLAIMS = [re.compile(c, re.I) for c in (
    rf"\b{OVER}[^.;|]{{0,80}}?\b{RIVAL}",                      # okl over a named rival
    rf"\b{RIVAL}('s)?[^.;|]{{0,40}}?\b(?:worse|weaker|slower|less \w+) than (?:okl|this)\b",
    rf"\b(?:better|superior) than theirs\b|\bunlike {RIVAL}\b[^.;|]{{0,60}}?\b(?:more|better|superior)\b",
    rf"\b(?:the|a) better memory\b|\bbest memory (?:tool|store|layer)\b|\bfirst {RIVAL} (?:to|that)\b",
    rf"\b(?:replac\w*|stand in for|substitute for)\b(?:\W+\w+){{0,4}}?\W+{RIVAL}",
    r"\breplac\w* them with (?:better|more)\b|\b(?:be )?used instead of (?:them|those tools|these tools)\b",
    rf"\bmakes? {RIVAL} (?:unnecessary|obsolete|redundant)\b|\b{RIVAL} (?:is|are|becomes?) (?:unnecessary|obsolete|redundant)\b",
    rf"\bswap (?:your|the) {RIVAL} for\b|\b(?:no longer|will not|won't) need\b[^.;|]{{0,20}}?{RIVAL}",
    rf"\bno (?:other )?{RIVAL} (?:verif|prov|check)\w*",
    r"\b(?:not|none of them (?:is|are)) worth composing\b|\bnobody else (?:does|offers|verifies|checks)\b"
    r"|\bnothing invalidates\b|\bno other tool\b|\bthe only (?:tool|memory)\b|\bfirst tool to\b",
)]
# A claim right after a negation, with only auxiliary words between, is the stance, not its
# opposite: "okl is no replacement for mem0", "it doesn't try to replace those tools". "There is
# no question that okl beats mem0" is not negated: other words stand between.
NEGATED = re.compile(r"\b(?:not|no|never|nor|without|\w+n't|cannot)(?:\s+(?:meant|intended|designed|built"
                     r"|trying|try|going|to|a|an|the|be|is|are|been|do|does|need|needs|direct|real))*\s+$", re.I)


def claims(text: str) -> list[str]:
    """Each sentence or table cell of `text` that claims okl over the memory tools."""
    found = []
    for unit in re.split(r"(?<=[.!?])\s+|\s\|\s", " ".join(text.split())):
        for claim in CLAIMS:
            hit = next((m for m in claim.finditer(unit) if not NEGATED.search(unit[:m.start()])), None)
            if hit:
                found.append(repr(hit.group(0)))
                break
    return found


if __name__ == "__main__":
    problems = []
    for doc, phrases in FRAMING.items():
        text = " ".join((REPO / doc).read_text().split())
        problems += [f"{doc} no longer says {p!r}" for p in phrases if p not in text]
    # Committed reality, not the working tree's untracked files (CLAUDE.md: audits read the repo).
    docs = [d for d in subprocess.run(["git", "-C", str(REPO), "ls-files", "README.md", "docs/"],
                                      capture_output=True, text=True, check=True).stdout.split() if d.endswith(".md")]
    for doc in docs:
        problems += [f"{doc}: {c}" for c in claims((REPO / doc).read_text())]
    if problems:
        sys.exit("POSITIONING CHANGED: " + "; ".join(problems))
    print("POSITIONING OK", len(docs), "docs")  # noqa: T201 - a check script reports on stdout
