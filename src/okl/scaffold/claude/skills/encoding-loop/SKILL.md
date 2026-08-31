---
name: encoding-loop
description: Use when you discover a rule, antipattern, or lesson worth keeping ("we should never write this again" / "we should always do this when") and need to encode it at the right surface and record it to the org knowledge layer. Fires on review findings, debugging discoveries, audits, and prior-art hits.
---

# Encoding loop — turn a finding into a durable, promoted rule

A trigger surfaced a candidate rule. The response is always the same two moves.

## 1. Pick the smallest sufficient surface (softest→strongest)

| # | Surface | Use when |
|---|---|---|
| 1 | `docs/` + diagram | the *why* needs more than a line, or reviewers need a picture |
| 2 | `CLAUDE.md` | every session needs it, always-on (keep it lean — prefer a rule file) |
| 2 | `.claude/rules/<area>.md` with `paths:` glob | scoped to a file category (loads only in context) |
| 3 | `.claude/skills/` or `.claude/commands/` | a multi-step procedure with real logic |
| 4 | `.coderabbit.yaml` path_instructions / `architecture-reviewer` checklist | catch at PR-review time |
| 5 | a gate in `gates/` + CI | mechanical, build-breaking — for rules that keep being broken |

Default to the *softest* surface that could hold the rule. **Promote down (toward 5) only as it
earns it** — a rule that keeps being violated moves to a sterner tier, not a sterner paragraph.
Most rules never leave tier 1, and that is fine.

## 2. Record it to the org layer so other repos inherit it

```
okl record --type <Defect|Gate|Rule|Claim|Retraction|Tombstone|Decision|PriorArt> \
  --title "..." --body "..." --scope <org|repo> [--verified]
```

- **`scope=org`** — a fact about the world: prior art, an API contract, a data-source gotcha, a
  portable gate. It will surface in every connected repo's `okl check`.
- **`scope=repo`** — a quirk true only of this codebase. Stays local.

If the finding retracts a prior claim, also add it to `registries/RETRACTIONS.md`; if it retires an
identifier, add it to `registries/tombstones.txt`. The CI gates then fail any doc that contradicts.

## 3. Verify the gate (if you made one)

A gate you have only seen pass is a gate you have not tested. Run it against the real drifted file
from git history and confirm it FAILS, then confirm it passes on the fix. Only then is it a gate.

## Gotchas
- A merged fix without the encoded rule is a half-finished job — the next instance slips through.
- A surface nobody runs is documentation, not enforcement. If it is not read/executed, it will drift.
- The drift you notice is the drift that embarrasses you; the flattering kind (stale "open" items)
  needs a mechanical `verified_at`/TTL check, not vigilance.
