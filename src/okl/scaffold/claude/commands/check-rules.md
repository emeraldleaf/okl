---
description: Run all mechanical drift-gates locally (the same set CI enforces) and print the worklist of any drift found.
disable-model-invocation: true
---

# /check-rules — run the drift-gates locally

Run the full gate suite and report, exactly as CI will:

```bash
bash gates/run-gates.sh --untracked
```

This runs:
- **retractions** — fails any doc that states a retracted claim without retracting it
- **tombstones** — fails any doc/comment/config resurrecting a retired identifier
- **doc-orphans** — fails any spec/ADR/audit not reachable from the docs hub
- **stale-open-items** — fails any registry item marked "open" that has been resolved
- **canon-size** — warns/fails if `CLAUDE.md` exceeds the size budget

<!-- <<FILL: STACK-SPECIFIC GATES>>  Add your build/analyzer/test gates here and in gates/run-gates.sh. -->

If anything fails, encode the fix at the smallest surface (see the `encoding-loop` skill) and
re-run. Do not merge with a red gate; a broken gate that reports "clean" is worse than no gate.
