#!/usr/bin/env python3
"""No seed record gated to a stack calls itself portable.

The check behind the `n_07faa4565128` lesson: read a record's own body before gating it, since
it may already declare its portability. Every committed record in seed/ with an `applies_to` is
read, and one whose title, symptom, body or fix calls it portable, or stack-, language- or
framework-agnostic, fails the check by name; "not portable" is a reason to gate, so it passes.
The first version read one record in one pack, so four breaks that gated other portable records
passed it (REPORT §4af, #318). "Any repo that ..." is not read as portable: a record can name a
stack-bound condition that way (geospatial `d14`).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORTABLE = re.compile(r"\bportab\w*|\b(stack|language|framework)-agnostic\b", re.I)
NEGATED = re.compile(r"\b(not|no|never|isn't|aren't)\s+$", re.I)   # "not portable" is the gate's reason

# Committed reality, not the working tree's untracked files (CLAUDE.md: audits read the repo).
packs = subprocess.run(["git", "-C", str(REPO), "ls-files", "seed/*.json"], capture_output=True, text=True, check=True)
gated, contradicted = 0, []
for pack in [REPO / f for f in packs.stdout.split()]:
    for node in json.loads(pack.read_text())["nodes"]:
        if not node.get("applies_to"):
            continue
        gated += 1
        text = " ".join(str(node.get(k) or "") for k in ("title", "symptom", "body", "fix"))
        if m := next((m for m in PORTABLE.finditer(text) if not NEGATED.search(text[:m.start()])), None):
            contradicted.append(f"{pack.name} {node.get('key')} (applies_to {node['applies_to']}, says {m.group(0)!r})")

if contradicted:
    sys.exit("PORTABLE RECORD GATED: " + "; ".join(contradicted))
print("PORTABLE RECORDS UNGATED", gated, "gated records read")  # noqa: T201 - a check script reports on stdout
