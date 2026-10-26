# How the bench's queries were made

Written before any query existed (2026-10-25), so the protocol can be checked against what it
produced.

## The corpus and the lessons queried

The corpus is the twelve committed seed packs (183 records). Every advice record in them (Rule,
Defect, Gate, Decision: 173 lessons) gets three queries. Claims, tombstones and prior art are in
the corpus as distractors and are never the answer.

## Who writes the queries, and what they see

Claude Sonnet sub-agents, in batches of up to 22 lessons. For each lesson the writer sees its
type, title, body, symptom and fix. It does **not** see the lesson's aliases or tags, the other
lessons in the store, any retrieval output, or any text an arm adds at index time. Write-time
expansions (generated "trigger" phrasings) are written later by a different model from the
lesson text alone, blind to these queries. That keeps the queries from echoing the index, the
bias that makes synthetic queries favour systems built from the same model's text (CIKM 2025,
arXiv 2506.10301).

## The three registers

1. **ticket**: a concrete work item a developer would hand a coding agent, where the lesson's
   rule or defect bites. It describes the task, not the pitfall.
2. **paraphrase**: the same kind of situation in other words. It uses no content word from the
   lesson's title (a word being two or more letters or digits), checked mechanically, and
   avoids the lesson's distinctive terms where a natural alternative exists.
3. **bug-report**: what a developer observes once the problem has happened (a symptom, an error,
   a behaviour), without naming the cause or the fix.

Every query is 6 to 40 words, never mentions the lesson or its advice, and is specific enough
that this lesson is the most useful one to brief, though other lessons may also apply.

## Splits

A lesson's three queries share its split, chosen by the parity of the SHA-256 of its id: 83
lessons (249 queries) for selection, 90 (270) held out. Choices are made on the selection split.
The held-out split is run once per pre-registered decision and is never used for tuning.

## The null prompts

Real prompts typed in Claude Code sessions on the machine that holds them, collected by
`extract_prompts.py`, labelled by a Sonnet sub-agent as NULL (it names no software task,
question, error or artifact of its own: acknowledgements, approvals, continuations, questions
about the conversation, references that only make sense with the previous turn) or TASK.
Only NULL prompts enter the null set. Beyond the Claude sub-agents that label or judge them, they
never leave that machine: nothing commits, publishes or quotes them; receipts carry their count,
a hash of the set, and how many were briefed anything.

## Known limits

- A model wrote the queries. Developers' real wording is rougher, which the null set and a later
  set of real task prompts partly address.
- Sonnet and the trigger writer are Claude models of one family, so shared phrasing habits are
  reduced, not removed.
- One governing lesson per query. A briefing that holds a different lesson that also applies is
  scored as a miss here. Judged precision on real prompts is a separate measure.
