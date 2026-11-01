# Where this sits (2026): a crowded space, entered anyway

Part of okl's documentation; the [README](../README.md) is the short version. This page holds the comparison the README used to carry in full; the README now keeps four lines and a table at a glance.


**This is not a novel idea, and you should know that before reading further.** Agent
memory is one of the most crowded categories in the field: mem0, Zep, Letta, and Cognee
on the infrastructure side, with enterprise knowledge graphs such as Utopia beside them;
Cursor Memories and Devin Knowledge built into the coding
agents; AGENTS.md / CLAUDE.md / rules files as the convention standard everyone already
uses; and the research literature (e.g. Codified Context, arXiv 2602.20478) arriving at
tiered knowledge + retrieval independently. "Give the agent your team's knowledge" is
the consensus position of 2026, not an insight.

**So why build it anyway?** Three honest reasons:

1. **The crowded half isn't this half.** Nearly all of that tooling solves
   *personalization* memory — facts extracted from conversations, per-user context,
   knowledge graphs of what the agent experienced. The *institutional* half — receipted
   engineering lessons with governance over who sees what, injected before work with
   teeth — is mostly served by hand-edited rules files, and inside Copilot by its
   repository memory. That gap is real even if the category isn't new.
2. **The bet: memories are treated like tests, not notes.** okl is not alone in tying
   memory to code: GitHub Copilot's memory (2026) cites the code lines behind each
   memory and has the agent re-read them before use, and driftlint fails CI when an
   instruction file names a path or command that no longer exists. okl's version is
   stricter for the lessons that matter. A lesson cites the source it governs and
   carries a verification receipt from a check you choose (`okl verify` — the CLI will
   not stamp without a run), can decay on a TTL, and goes stale *loudly*:
   `okl drift --gate` blocks the push (or fails CI, with `--ci`) when governed code
   changed after the lesson was last verified, or it was never verified. Most tools in the
   table below accumulate, decay with time, or close a memory when a newer fact contradicts
   it; the ones that tie a memory to code check it by re-reading the
   code, checking a reference, or noticing a file changed, not by running your check.
   The whole repo is plumbing to get that bet in front of an agent
   before the first line of code is written.
3. **Building it was the point.** This repo exists to make a working method concrete —
   and the things it surfaced would not have come from adopting a product: the eval
   receipts in `evals/`, the store carrying its own failure log, and the end-to-end
   test that caught the briefing being delivered to a channel the model never reads
   (`evals/REPORT.md` §8). Wiring a vendor SDK would have taught none of that.

| Tool / convention | What it remembers | What invalidates a memory |
|---|---|---|
| mem0 / Zep / Letta / Cognee | extracted facts, conversation graphs, agent-curated tiers | a newer fact that contradicts one: Zep closes it on a timeline of when it held, mem0's model updates or deletes it. Nothing tied to your code |
| Utopia (enterprise world model) | entities and facts extracted from business documents into an ontology-driven, bitemporal graph | a newer document's contradicting fact can close the old one (or both are kept, or the new one is rejected), with when each held and when it was learned; doubtful cases go to a person. Nothing tied to your code |
| Cursor Memories / Devin Knowledge | per-project conventions and pinned notes | manual editing |
| GitHub Copilot Memory (2026) | repo facts the agent saves as it works, each citing the code lines behind it; shared by Copilot's coding agent, CLI and code review | the agent re-reads the cited lines before use and replaces a contradicted memory; memories expire unless re-confirmed — a model's judgment at use time, Copilot only, no CI gate |
| driftlint, agents-lint, scavi (instruction-file linters) | nothing of their own: they check the claims already in CLAUDE.md / AGENTS.md (driftlint also syncs approved facts into them) | a referenced path, command, link or import that no longer exists; driftlint fails CI. The reference checks don't test whether a rule still holds; driftlint's optional `--llm` mode asks a model whether the code contradicts a prose claim |
| AGENTS.md / CLAUDE.md / rules files | hand-written canon, loaded whole | hand-editing; no per-task selection |
| claude-mem / agentmemory (Claude Code plugins) | every tool call, compressed into observations by a model; agentmemory adds confidence and decay | file age (claude-mem skips a note when its file changed); time-based decay (agentmemory) — nothing re-checks a memory |
| ECC (skills + "instincts") | instincts learned from observed tool use, weighted by a model-scored confidence | confidence decay, applied by prompt — no check proves an instinct |
| beads | work items and short `bd remember` notes — a task tracker, not a lesson store | closing the issue |
| **okl** | **typed, scoped lessons (Defect / Rule / Decision …), selected per task, fail-closed** | **the drift gate: a lesson whose governed source changed after its last verification (or that was never verified) blocks the push, or fails CI** |

**Read against the Claude Code memory plugins** (claude-mem, agentmemory, ECC, beads — their
source, September 2026): they are ahead on capture, retrieval engineering, install polish
and reach across agents, and okl is not trying to catch them there. None re-checks that a
memory is still true, ties one to the code it describes, or measures whether memory
improves outcomes — claude-mem's "~10x" is a 5-query code-search benchmark, agentmemory's
evals are retrieval-only. Their capture also costs model calls (claude-mem runs a model per
tool call; agentmemory's lessons need an API key); okl requires none. claude-mem remembers
what happened; okl keeps what must stay true, and proves it.

**Running one of them alongside okl** works, with three known collisions: okl's Claude Code Stop hook
blocks the first stop, so their Stop hooks run twice; capture-everything tools record
`okl record` too, so a lesson lands in two stores; and each injects its own context beside
okl's briefing. `okl doctor` names whichever is installed and what to do about it.

## Can I use mem0 / Zep / Letta instead? Or alongside?

**Instead — yes, if your problem is theirs.** If you want semantic recall over what an
agent has seen, per-user personalization, or conversation-scale memory, use them;
they're better at it, and this deliberately isn't that (no embeddings, by
[recorded decision](decisions/2026-07-17-flat-retrieval-until-scale.md)).

**Alongside — they compose, because they're different layers.** Memory infrastructure
remembers what the agent *experienced*; this governs what the org has *verified*. A
reasonable stack runs both: mem0/Zep for recall, okl for the fail-closed pre-task
briefing, the drift gate (before the push, or in CI), and the record/verify loop.

**On top — the discipline is portable; the database is deliberately boring.** The parts
worth stealing are the typed schema, the org/repo scope boundary, verification-with-
receipts, and the fail-closed delivery — not the SQLite file. If your org already runs
a memory backend, reimplementing this loop on top of it is a reasonable weekend; what
you'd be adopting is the discipline, not the storage.
