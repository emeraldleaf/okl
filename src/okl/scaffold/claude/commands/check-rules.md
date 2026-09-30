---
description: Run all mechanical drift-gates locally (the same set CI enforces) and print the worklist of any drift found.
disable-model-invocation: true
---

# /check-rules — run the drift-gates locally

Needs the method kit that `okl scaffold .` installs (`gates/`, `registries/`, the `encoding-loop`
skill); without it there is nothing to run.

Run the full gate suite and report, exactly as CI will:

```bash
bash gates/run-gates.sh
```

This runs:
- **retractions** — fails any doc that restates a quoted claim from `registries/RETRACTIONS.md` verbatim
- **tombstones** — fails any doc/source/config resurrecting a retired identifier
- **doc-orphans** — fails any doc or image under `docs/` not linked from a hub file or another doc
- **links** — fails any markdown link to a local file that does not exist
- **diagram-pairs** — fails any editable diagram source with no rendered sibling
- **canon-size** — warns/fails if `CLAUDE.md` exceeds the size budget

<!-- <<FILL: STACK-SPECIFIC GATES>>  Add your build/analyzer/test gates here and in gates/run-gates.sh. -->

If anything fails, encode the fix at the smallest surface (see the `encoding-loop` skill) and
re-run. Do not merge with a red gate; a broken gate that reports "clean" is worse than no gate.
