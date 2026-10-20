# Subagents and small context budgets

Part of okl's documentation; the [README](../README.md) is the short version. The measured sizes are in the README's "What it costs"; this page is the cap, what the compact form drops, and how to wire a subagent.

The full briefing is itself capped: `check` keeps the top `--limit` records (12 by
default) from the ranked, filtered set and says how many it trimmed. Historically, before
that cutoff existed, one task on this repo's store at the time returned 20 records and
~4,400 tokens. The cutoff did
cost one retrieval: `exit_code_trust`'s governing rule ranks below the top 12 for that
task's wording. Run outcomes hid it (the briefing still prevented the defect, through
other records); `evals/preflight.py` found it by asking directly whether each task's rule
is in its briefing, and it is kept in a named register rather than silently. See
[evals/REPORT.md](../evals/REPORT.md) §4b's correction.

What it drops: the bucketed sections (Decisions among them), the prose bodies explaining *why* each record
exists, prior-art notes, and the stale-record footer. What it keeps is what changes
behaviour: the verb, the symptom to watch for, and the fix.

**Wiring it into a subagent.** Three ways, in order of how much enforcement you get:

1. **The MCP tool** — `okl_check(task=..., compact=True, limit=3)`. Any subagent with
   MCP access can call it. Discretionary: the agent has to choose to.
2. **In the subagent's prompt** — have the spawning agent run `okl check --format
   actions --limit 3` and paste the result into the subtask description. Not
   discretionary, and it costs the parent almost nothing.
3. **A wrapper script** that runs the check and prepends it to whatever prompt it is
   handed. This is the enforced version for orchestration you control.

**A caveat worth stating.** `--limit` caps how many records the briefing draws on, and
ranking decides which survive. If a task's most relevant rule ranks fourth and you ask
for three, you will not see it, and nothing will tell you. The full briefing exists
because it does not make that trade. Use the compact form where a token budget forces
the choice, not by default.
