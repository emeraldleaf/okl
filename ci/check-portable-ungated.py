#!/usr/bin/env python3
"""No seed record gated to a stack calls itself portable.

The check behind the `n_07faa4565128` lesson: read a record's own body before gating it, since
it may already declare its portability. Every record in seed/ with an `applies_to` is read, and
one whose title, symptom, body or fix calls it portable, or stack- or language-agnostic, fails
the check by name. The first version read one record in one pack, so four breaks that gated
other portable records passed it (REPORT §4af, #318). "Any repo that ..." is not read as
portable: a record can name a stack-bound condition that way (geospatial `d14`).
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORTABLE = re.compile(r"\bportab\w*|\b(stack|language)-agnostic\b", re.I)

gated, contradicted = 0, []
for pack in sorted((REPO / "seed").glob("*.json")):
    for node in json.loads(pack.read_text())["nodes"]:
        if not node.get("applies_to"):
            continue
        gated += 1
        text = " ".join(str(node.get(k) or "") for k in ("title", "symptom", "body", "fix"))
        if m := PORTABLE.search(text):
            contradicted.append(f"{pack.name} {node.get('key')} (applies_to {node['applies_to']}, says {m.group(0)!r})")

if contradicted:
    sys.exit("PORTABLE RECORD GATED: " + "; ".join(contradicted))
print("PORTABLE RECORDS UNGATED", gated, "gated records read")  # noqa: T201 - a check script reports on stdout
